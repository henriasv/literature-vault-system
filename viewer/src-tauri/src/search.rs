use anyhow::{anyhow, Context, Result};
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};

use crate::vault::embeddings_db;

const EMBED_SERVER: &str = "http://127.0.0.1:5817";

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EmbedServerHealth {
    pub ok: bool,
    pub default: String,
    pub registered: Vec<String>,
    pub loaded: Vec<String>,
    #[serde(default)]
    pub uptime_sec: f64,
    #[serde(default)]
    pub idle_sec: f64,
    /// Set when the request itself failed (server down etc).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchHit {
    pub citekey: String,
    pub score: f32,
}

#[derive(Debug, Deserialize)]
struct EmbedResponse {
    vectors: Vec<Vec<f32>>,
    model: String,
}

#[derive(Debug, Deserialize)]
struct HealthRaw {
    ok: bool,
    default: String,
    #[serde(default)]
    registered: Vec<String>,
    #[serde(default)]
    loaded: Vec<String>,
    #[serde(default)]
    uptime_sec: f64,
    #[serde(default)]
    idle_sec: f64,
}

/// `embed_corpus.py` derives table names with `re.sub(r"[^a-zA-Z0-9]", "_", model_id)`.
/// Mirror exactly so we hit the same table.
fn safe_model_id(model_id: &str) -> String {
    model_id
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() { c } else { '_' })
        .collect()
}

fn vec_to_bytes(v: &[f32]) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(v.len() * 4);
    for f in v {
        bytes.extend_from_slice(&f.to_le_bytes());
    }
    bytes
}

async fn fetch_health() -> Result<EmbedServerHealth> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(2))
        .build()
        .context("build reqwest client")?;
    let res = client
        .get(format!("{EMBED_SERVER}/health"))
        .send()
        .await
        .context("GET /health")?;
    let raw: HealthRaw = res.json().await.context("parse /health body")?;
    Ok(EmbedServerHealth {
        ok: raw.ok,
        default: raw.default,
        registered: raw.registered,
        loaded: raw.loaded,
        uptime_sec: raw.uptime_sec,
        idle_sec: raw.idle_sec,
        error: None,
    })
}

async fn embed_query(query: &str) -> Result<(Vec<f32>, String)> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(60))
        .build()
        .context("build reqwest client")?;
    let body = serde_json::json!({
        "texts": [query],
        "prompt": "query",
    });
    let res = client
        .post(format!("{EMBED_SERVER}/embed"))
        .json(&body)
        .send()
        .await
        .context("POST /embed")?;
    let status = res.status();
    if !status.is_success() {
        let text = res.text().await.unwrap_or_default();
        return Err(anyhow!("/embed returned {status}: {text}"));
    }
    let parsed: EmbedResponse = res.json().await.context("parse /embed body")?;
    let vec = parsed
        .vectors
        .into_iter()
        .next()
        .ok_or_else(|| anyhow!("/embed returned no vectors"))?;
    Ok((vec, parsed.model))
}

fn knn_lookup(model: &str, query_vec: &[f32], limit: u32) -> Result<Vec<SearchHit>> {
    let db = embeddings_db();
    if !db.is_file() {
        return Err(anyhow!("embeddings.db not found at {}", db.display()));
    }
    let conn = Connection::open_with_flags(
        &db,
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY | rusqlite::OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .with_context(|| format!("open {} read-only", db.display()))?;
    let table = format!("vec_papers__{}", safe_model_id(model));
    // sqlite-vec MATCH expects k as part of the WHERE clause.
    let sql = format!(
        "SELECT citekey, distance FROM {table} \
         WHERE embedding MATCH ?1 AND k = ?2 ORDER BY distance"
    );
    let blob = vec_to_bytes(query_vec);
    let mut stmt = conn
        .prepare(&sql)
        .with_context(|| format!("prepare KNN query against {table}"))?;
    let rows = stmt
        .query_map(params![blob, limit as i64], |row| {
            Ok(SearchHit {
                citekey: row.get(0)?,
                score: row.get::<_, f64>(1)? as f32,
            })
        })
        .context("query KNN")?;
    let mut hits = Vec::new();
    for h in rows {
        hits.push(h?);
    }
    Ok(hits)
}

#[tauri::command]
pub async fn embed_server_health() -> Result<EmbedServerHealth, String> {
    match fetch_health().await {
        Ok(h) => Ok(h),
        Err(e) => Ok(EmbedServerHealth {
            ok: false,
            default: String::new(),
            registered: Vec::new(),
            loaded: Vec::new(),
            uptime_sec: 0.0,
            idle_sec: 0.0,
            error: Some(format!("{e:#}")),
        }),
    }
}

/// Internal helper used by both the Tauri command and integration tests.
pub async fn search_semantic_impl(query: String, limit: u32) -> Result<Vec<SearchHit>> {
    let (vec, model) = embed_query(&query).await?;
    let hits = tokio::task::spawn_blocking(move || knn_lookup(&model, &vec, limit))
        .await
        .map_err(|e| anyhow!("join error: {e}"))??;
    Ok(hits)
}

#[tauri::command]
pub async fn search_semantic(query: String, limit: u32) -> Result<Vec<SearchHit>, String> {
    search_semantic_impl(query, limit)
        .await
        .map_err(|e| format!("{e:#}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn safe_model_id_matches_python() {
        assert_eq!(safe_model_id("nemotron-8b"), "nemotron_8b");
        assert_eq!(safe_model_id("embeddinggemma-300m"), "embeddinggemma_300m");
        assert_eq!(safe_model_id("bge-large-en-v1.5"), "bge_large_en_v1_5");
    }

    /// Hits the live embed server + embeddings.db. Requires the server on :5817 and
    /// embeddings.db populated. Auto-extension must be registered first.
    #[tokio::test]
    #[ignore]
    async fn semantic_search_end_to_end() {
        crate::register_sqlite_vec();
        let hits = search_semantic_impl("ice nucleation in clay".into(), 5)
            .await
            .expect("semantic search");
        assert!(!hits.is_empty(), "expected at least one hit");
        for h in &hits {
            println!("  {} score={}", h.citekey, h.score);
        }
    }
}

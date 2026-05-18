use std::path::{Path, PathBuf};
use std::process::Command;

use anyhow::{anyhow, Context, Result};
use serde::{Deserialize, Serialize};

use crate::vault::{inbox_dir, vault_root};

fn ensure_inbox() -> Result<PathBuf> {
    let dir = inbox_dir();
    std::fs::create_dir_all(&dir)
        .with_context(|| format!("create_dir_all {}", dir.display()))?;
    Ok(dir)
}

/// Copy `src` to `inbox/{filename}` with a `-N` suffix on collision.
/// Returns the resulting path inside the inbox.
fn copy_unique_into_inbox(src: &Path, inbox: &Path) -> Result<PathBuf> {
    let stem = src
        .file_stem()
        .and_then(|s| s.to_str())
        .ok_or_else(|| anyhow!("path has no filename: {}", src.display()))?
        .to_string();
    let ext = src
        .extension()
        .and_then(|s| s.to_str())
        .map(|s| s.to_string());
    let with_ext = |stem: &str| -> PathBuf {
        let mut name = stem.to_string();
        if let Some(e) = &ext {
            name.push('.');
            name.push_str(e);
        }
        inbox.join(name)
    };
    let mut candidate = with_ext(&stem);
    let mut n: u32 = 1;
    while candidate.exists() {
        candidate = with_ext(&format!("{stem}-{n}"));
        n += 1;
        if n > 9999 {
            return Err(anyhow!("too many collisions for {}", src.display()));
        }
    }
    // We don't use atomic_write for binary copies — use a tempfile in the inbox dir
    // and rename, which still survives a crash mid-copy.
    let tmp = tempfile::Builder::new()
        .prefix(".inbox-")
        .suffix(".tmp")
        .tempfile_in(inbox)
        .with_context(|| format!("tempfile in {}", inbox.display()))?;
    let tmp_path = tmp.path().to_path_buf();
    std::fs::copy(src, &tmp_path)
        .with_context(|| format!("copy {} → {}", src.display(), tmp_path.display()))?;
    tmp.persist(&candidate)
        .with_context(|| format!("persist {}", candidate.display()))?;
    Ok(candidate)
}

pub fn drop_to_inbox_impl(pdf_paths: Vec<String>) -> Result<Vec<String>> {
    let inbox = ensure_inbox()?;
    let mut out = Vec::with_capacity(pdf_paths.len());
    for p in pdf_paths {
        let src = PathBuf::from(&p);
        if !src.is_file() {
            return Err(anyhow!("not a file: {}", src.display()));
        }
        let dest = copy_unique_into_inbox(&src, &inbox)?;
        out.push(dest.to_string_lossy().into_owned());
    }
    Ok(out)
}

#[tauri::command]
pub fn drop_to_inbox(pdf_paths: Vec<String>) -> Result<Vec<String>, String> {
    drop_to_inbox_impl(pdf_paths).map_err(|e| format!("{e:#}"))
}

/* ---------- auto-file path ----------------------------------------------
 *
 * The vault repo carries two deterministic Python scripts that own the
 * canonical filing logic — same scripts the agent invokes:
 *
 *   scripts/extract_ids.py <pdf>  → JSON {doi, arxiv_id, source}
 *   scripts/file_paper.py --pdf <path> --doi <doi> [--arxiv <id>]
 *                                  → JSON {citekey, …} or {duplicate, …}
 *
 * The viewer never re-implements the citekey scheme, the BibTeX
 * generation, or the dedup table — it just shells out and parses the
 * structured output. That way a PDF dropped via the viewer ends up
 * indistinguishable from one filed by the agent.
 *
 * Runtime requirement: the vault user has Python ≥ 3.12 and `pypdf`
 * installed (declared in each script's PEP-723 inline metadata, so
 * `uv run` handles deps automatically; plain `python3` also works if
 * the deps are in the active env).
 */

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FilingOutcome {
    /// Absolute path of the PDF as it sits in the Inbox right now.
    pub inbox_path: String,
    pub status: FilingStatus,
    /// Canonical citekey on success or duplicate; None for no-id / errors.
    pub citekey: Option<String>,
    /// Title from CrossRef on success; None otherwise. Frontend uses this
    /// to render a friendly toast like "Filed: <title>".
    pub title: Option<String>,
    /// Human-readable detail — DOI we tried, error message, etc.
    pub detail: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum FilingStatus {
    /// PaperNotes/{citekey}.md, Bibfiles/{citekey}.bib, PDFs/{citekey}.pdf
    /// were all written; index.json updated. PDF moved out of Inbox.
    Filed,
    /// Already known — index.json had a hit on DOI/arXiv/sha. PDF stays
    /// in the Inbox so the user can manually clean up.
    Duplicate,
    /// extract_ids.py couldn't find any identifier; PDF stays in Inbox.
    NoIdentifier,
    /// file_paper.py exited with an error; PDF stays in Inbox. `detail`
    /// carries the stderr line so the user can diagnose.
    Error,
    /// scripts/{extract_ids,file_paper}.py don't exist in this vault —
    /// auto-filing isn't available. PDF stays in Inbox.
    ScriptsMissing,
}

#[derive(Debug, Deserialize)]
struct ExtractIdsOut {
    doi: Option<String>,
    arxiv_id: Option<String>,
}

#[derive(Debug, Deserialize)]
struct FilePaperOut {
    #[serde(default)]
    duplicate: bool,
    citekey: Option<String>,
    existing_citekey: Option<String>,
    bibtex: Option<String>,
}

pub(crate) fn scripts_dir() -> PathBuf {
    vault_root().join("scripts")
}

/// Build an enriched PATH that prepends the bin directories
/// Homebrew + user-local installers commonly use. macOS apps launched
/// from Finder / Applications inherit only launchd's minimal default
/// PATH (typically `/usr/bin:/bin:/usr/sbin:/sbin`), so `uv` /
/// `python3` installed under `/opt/homebrew/bin` or `~/.local/bin`
/// aren't found — that's the "drag-drop does nothing in production"
/// symptom. Dev mode is unaffected because `npm run tauri dev`
/// inherits the user's shell PATH.
fn enriched_path() -> std::ffi::OsString {
    let mut paths: Vec<PathBuf> = Vec::new();
    // Apple Silicon Homebrew first; falls through to Intel Homebrew
    // and user-local bins. Anything already in PATH appended after.
    let candidates: [&str; 4] = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/opt/homebrew/sbin",
        "/usr/local/sbin",
    ];
    for p in candidates.iter() {
        paths.push(PathBuf::from(p));
    }
    if let Some(home) = std::env::var_os("HOME") {
        let home = PathBuf::from(&home);
        paths.push(home.join(".local").join("bin"));
        paths.push(home.join(".cargo").join("bin"));
    }
    if let Some(existing) = std::env::var_os("PATH") {
        for p in std::env::split_paths(&existing) {
            if !paths.contains(&p) {
                paths.push(p);
            }
        }
    }
    std::env::join_paths(paths).unwrap_or_else(|_| {
        std::env::var_os("PATH").unwrap_or_else(|| std::ffi::OsString::from(""))
    })
}

pub(crate) fn run_script(script: &str, args: &[&str]) -> Result<String> {
    let script_path = scripts_dir().join(script);
    if !script_path.is_file() {
        return Err(anyhow!("script not found: {}", script_path.display()));
    }
    let enriched = enriched_path();
    // Prefer `uv run` (handles PEP-723 inline deps automatically). Fall back
    // to plain `python3` if uv isn't on PATH; that requires pypdf to be in
    // whatever environment python3 resolves to.
    let try_cmd = |program: &str, prefix: &[&str]| -> Option<Result<std::process::Output>> {
        let mut cmd = Command::new(program);
        for a in prefix { cmd.arg(a); }
        cmd.arg(&script_path);
        for a in args { cmd.arg(a); }
        cmd.current_dir(vault_root());
        // Map vault root through env in case the script reads it.
        cmd.env("LITERATURE_VAULT_ROOT", vault_root());
        // Enriched PATH so Finder-launched builds can still find
        // /opt/homebrew/bin/uv etc.
        cmd.env("PATH", &enriched);
        match cmd.output() {
            Ok(o) => Some(Ok(o)),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => None,
            Err(e) => Some(Err(anyhow!("{program} failed: {e}"))),
        }
    };
    let output = try_cmd("uv", &["run"])
        .or_else(|| try_cmd("python3", &[]))
        .or_else(|| try_cmd("python", &[]))
        .ok_or_else(|| anyhow!("neither `uv` nor `python3` found on PATH"))??;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).into_owned();
        // file_paper.py uses exit 1 for "duplicate" — we surface that as a
        // structured result, not an error. Detect via the stdout JSON.
        if output.status.code() == Some(1) && !output.stdout.is_empty() {
            return Ok(String::from_utf8_lossy(&output.stdout).into_owned());
        }
        return Err(anyhow!("{script} failed: {stderr}"));
    }
    Ok(String::from_utf8_lossy(&output.stdout).into_owned())
}

/// Run file_paper.py for a PDF whose DOI/arXiv we already know (either
/// from extract_ids.py or supplied by the user via the CrossRef search
/// assist). Translates the script's stdout / exit code into a
/// FilingOutcome. Used by both auto_file_one and the manual filing path.
fn run_file_paper(pdf: &Path, doi: &str, arxiv: &str) -> FilingOutcome {
    let mut out = FilingOutcome {
        inbox_path: pdf.to_string_lossy().into_owned(),
        status: FilingStatus::Error,
        citekey: None,
        title: None,
        detail: None,
    };

    if !scripts_dir().join("file_paper.py").is_file() {
        out.status = FilingStatus::ScriptsMissing;
        out.detail = Some("scripts/file_paper.py not found in vault".into());
        return out;
    }

    let mut args: Vec<String> = vec![
        "--pdf".into(),
        pdf.to_string_lossy().into_owned(),
    ];
    if !doi.is_empty() {
        args.push("--doi".into());
        args.push(doi.to_string());
    }
    if !arxiv.is_empty() {
        args.push("--arxiv".into());
        args.push(arxiv.to_string());
    }
    let args_ref: Vec<&str> = args.iter().map(|s| s.as_str()).collect();
    let file_json = match run_script("file_paper.py", &args_ref) {
        Ok(s) => s,
        Err(e) => {
            out.detail = Some(format!("file_paper.py: {e}"));
            return out;
        }
    };
    let parsed: FilePaperOut = match serde_json::from_str(file_json.trim()) {
        Ok(v) => v,
        Err(e) => {
            out.detail = Some(format!("parse file_paper output: {e} — raw: {file_json}"));
            return out;
        }
    };

    if parsed.duplicate {
        out.status = FilingStatus::Duplicate;
        out.citekey = parsed.existing_citekey;
        out.detail = Some(if !doi.is_empty() { format!("doi: {doi}") } else { format!("arxiv: {arxiv}") });
        return out;
    }

    out.status = FilingStatus::Filed;
    out.citekey = parsed.citekey;
    let _ = parsed.bibtex;
    out
}

fn auto_file_one(pdf: &Path) -> FilingOutcome {
    if !scripts_dir().join("file_paper.py").is_file() {
        return FilingOutcome {
            inbox_path: pdf.to_string_lossy().into_owned(),
            status: FilingStatus::ScriptsMissing,
            citekey: None,
            title: None,
            detail: Some("scripts/file_paper.py not found in vault".into()),
        };
    }

    // 1. Extract DOI / arXiv from the PDF.
    let extract_json = match run_script("extract_ids.py", &[&pdf.to_string_lossy()]) {
        Ok(s) => s,
        Err(e) => {
            return FilingOutcome {
                inbox_path: pdf.to_string_lossy().into_owned(),
                status: FilingStatus::Error,
                citekey: None,
                title: None,
                detail: Some(format!("extract_ids.py: {e}")),
            };
        }
    };
    let ids: ExtractIdsOut = match serde_json::from_str(extract_json.trim()) {
        Ok(v) => v,
        Err(e) => {
            return FilingOutcome {
                inbox_path: pdf.to_string_lossy().into_owned(),
                status: FilingStatus::Error,
                citekey: None,
                title: None,
                detail: Some(format!("parse extract_ids output: {e}")),
            };
        }
    };
    let doi = ids.doi.unwrap_or_default();
    let arxiv = ids.arxiv_id.unwrap_or_default();
    if doi.is_empty() && arxiv.is_empty() {
        return FilingOutcome {
            inbox_path: pdf.to_string_lossy().into_owned(),
            status: FilingStatus::NoIdentifier,
            citekey: None,
            title: None,
            detail: Some("no DOI or arXiv ID found in PDF".into()),
        };
    }

    // 2. File it with the extracted identifier.
    run_file_paper(pdf, &doi, &arxiv)
}

/* ---------- CrossRef search assist --------------------------------------
 *
 * When extract_ids.py can't find a DOI in a PDF (e.g. a scanned document
 * or a preprint), the user supplies title / author / year hints in the
 * Inbox UI and we shell out to scripts/crossref_search.py. The script
 * returns a JSON array of candidates ranked by CrossRef's own score;
 * the user picks one, and we then file the PDF via run_file_paper with
 * the chosen DOI — identical to the auto-file path from that point on,
 * so the citekey scheme remains the agent's canonical one. */

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CrossrefCandidate {
    pub doi: Option<String>,
    pub title: Option<String>,
    pub first_author: Option<String>,
    pub n_authors: Option<i64>,
    pub year: Option<i64>,
    #[serde(rename = "type")]
    pub kind: Option<String>,
    pub score: Option<f64>,
}

#[tauri::command]
pub async fn search_crossref(
    title: Option<String>,
    author: Option<String>,
    query: Option<String>,
    year: Option<i64>,
) -> Result<Vec<CrossrefCandidate>, String> {
    if !scripts_dir().join("crossref_search.py").is_file() {
        return Err("scripts/crossref_search.py not found in vault".into());
    }
    let mut args: Vec<String> = Vec::new();
    if let Some(t) = title.as_ref().filter(|s| !s.trim().is_empty()) {
        args.push("--title".into());
        args.push(t.clone());
    }
    if let Some(a) = author.as_ref().filter(|s| !s.trim().is_empty()) {
        args.push("--author".into());
        args.push(a.clone());
    }
    if let Some(q) = query.as_ref().filter(|s| !s.trim().is_empty()) {
        args.push("--query".into());
        args.push(q.clone());
    }
    if let Some(y) = year {
        args.push("--year".into());
        args.push(y.to_string());
    }
    if args.is_empty() {
        return Err("provide at least one of title / author / query".into());
    }
    // The script does a synchronous HTTP request to CrossRef (5–15s typical).
    // Run it on the blocking-task thread pool so the Tauri runtime and the
    // webview stay responsive — clicking Cancel in the UI can return while
    // this thread keeps draining the (now-discarded) result.
    let out = tokio::task::spawn_blocking(move || {
        let args_ref: Vec<&str> = args.iter().map(|s| s.as_str()).collect();
        run_script("crossref_search.py", &args_ref).map_err(|e| format!("{e:#}"))
    })
    .await
    .map_err(|e| format!("crossref_search join error: {e}"))??;
    serde_json::from_str(out.trim())
        .map_err(|e| format!("parse crossref_search output: {e} — raw: {out}"))
}

/// File an Inbox PDF with a DOI the user picked from the CrossRef
/// search results. Same canonical path as auto-file from `run_file_paper`
/// onwards, so the citekey + BibTeX come out identical to an
/// auto-filed paper.
#[tauri::command]
pub fn inbox_file_with_doi(path: String, doi: String) -> Result<FilingOutcome, String> {
    let pdf = PathBuf::from(&path);
    if !pdf.is_file() {
        return Err(format!("not a file: {path}"));
    }
    if doi.trim().is_empty() {
        return Err("DOI is required".into());
    }
    Ok(run_file_paper(&pdf, doi.trim(), ""))
}

/// Result of `scripts/extract_ids.py` on an arbitrary PDF. Either id may be
/// null; the script's three-tier scan goes metadata → text → raw bytes.
#[derive(Debug, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExtractedIds {
    pub doi: Option<String>,
    pub arxiv_id: Option<String>,
    /// "metadata" | "text" | "bytes" | "none" — where the id was found, or
    /// "none" if neither was located. Useful to display so the user can tell
    /// "from metadata" (reliable) from "from raw bytes" (could be a false
    /// positive matching a reference in the bibliography).
    pub source: String,
}

/// Run `extract_ids.py` on any PDF path. Surface to the frontend as the
/// "Auto-detect" tab in the Re-identify modal — gives the user a one-click
/// way to re-run the deterministic ID-extraction step against the existing
/// PDF (the agent might have picked the wrong DOI initially; running this
/// again won't change anything unless the PDF text changed, but it's a useful
/// sanity check, and an arXiv id found here can be filed with `--arxiv`).
#[tauri::command]
pub async fn extract_ids_from_pdf(path: String) -> Result<ExtractedIds, String> {
    let pdf = PathBuf::from(&path);
    if !pdf.is_file() {
        return Err(format!("not a file: {path}"));
    }
    if !scripts_dir().join("extract_ids.py").is_file() {
        return Err("scripts/extract_ids.py not found in vault".into());
    }
    let path_owned = path.clone();
    let out = tokio::task::spawn_blocking(move || {
        run_script("extract_ids.py", &[&path_owned])
            .map_err(|e| format!("extract_ids: {e:#}"))
    })
    .await
    .map_err(|e| format!("extract_ids join error: {e}"))??;
    serde_json::from_str(out.trim())
        .map_err(|e| format!("parse extract_ids output: {e} — raw: {out}"))
}

/// Full CrossRef record (or DataCite fallback) for a single DOI.
/// Returned as a raw JSON string so the viewer can render it as-is
/// in the "Details" panel on each CrossRef search candidate — no
/// shape promise from us, just whatever CrossRef/DataCite knows.
#[tauri::command]
pub async fn fetch_crossref_record(doi: String) -> Result<String, String> {
    if !scripts_dir().join("crossref_record.py").is_file() {
        return Err("scripts/crossref_record.py not found in vault".into());
    }
    let doi_owned = doi.clone();
    let out = tokio::task::spawn_blocking(move || {
        run_script("crossref_record.py", &["--doi", &doi_owned])
            .map_err(|e| format!("crossref_record: {e:#}"))
    })
    .await
    .map_err(|e| format!("crossref_record join error: {e}"))??;
    Ok(out)
}

/// Best-guess metadata extraction for a PDF that the auto-file
/// pipeline couldn't identify (no DOI / no CrossRef / no DataCite).
/// Shells out to `scripts/extract_pdf_meta.py --format bibtex`, which
/// reads /Info, XMP, and first-page text and returns a `@misc{…}`
/// stub. The viewer pre-fills the manual-entry textarea with this
/// stub so the user only edits, not types from scratch. Returns
/// empty string when the script isn't installed or extraction fails
/// — caller falls back to the static template.
#[tauri::command]
pub async fn inbox_extract_bibtex_stub(path: String) -> Result<String, String> {
    let pdf = PathBuf::from(&path);
    if !pdf.is_file() {
        return Err(format!("not a file: {path}"));
    }
    if !scripts_dir().join("extract_pdf_meta.py").is_file() {
        return Ok(String::new());
    }
    let path_owned = path.clone();
    let out = tokio::task::spawn_blocking(move || {
        run_script("extract_pdf_meta.py", &["--format", "bibtex", &path_owned])
            .map_err(|e| format!("extract_pdf_meta: {e:#}"))
    })
    .await
    .map_err(|e| format!("extract_pdf_meta join error: {e}"))??;
    Ok(out.trim_end().to_string())
}

/// File an Inbox PDF from a user-typed BibTeX entry. For sources
/// CrossRef doesn't index (books, theses, preprints without DOI, web
/// pages, …). Shells out to `scripts/manual_file.py`, which owns the
/// canonical citekey logic — same as `file_paper.py` does for the
/// CrossRef path. The user's BibTeX is preserved verbatim except for
/// the @type{KEY, …} header, which gets rewritten to the canonical
/// citekey computed from the parsed metadata (author/year + title-slug
/// or DOI suffix). That guarantees a viewer-filed manual entry is
/// indistinguishable from one the agent would produce.
#[tauri::command]
pub fn inbox_file_with_bibtex(path: String, bibtex: String) -> Result<FilingOutcome, String> {
    let pdf = PathBuf::from(&path);
    if !pdf.is_file() {
        return Err(format!("not a file: {path}"));
    }
    if bibtex.trim().is_empty() {
        return Err("BibTeX entry is required".into());
    }
    if !scripts_dir().join("manual_file.py").is_file() {
        return Ok(FilingOutcome {
            inbox_path: path,
            status: FilingStatus::ScriptsMissing,
            citekey: None,
            title: None,
            detail: Some("scripts/manual_file.py not found in vault".into()),
        });
    }

    /* manual_file.py takes the BibTeX over stdin (--bibtex-file -) to
     * avoid shell-escaping headaches with multi-line content. */
    let script_path = scripts_dir().join("manual_file.py");
    let enriched = enriched_path();
    let try_run = |program: &str, prefix: &[&str]| -> Option<std::io::Result<std::process::Output>> {
        let mut cmd = Command::new(program);
        for a in prefix {
            cmd.arg(a);
        }
        cmd.arg(&script_path);
        cmd.arg("--pdf").arg(&path);
        cmd.arg("--bibtex-file").arg("-");
        cmd.current_dir(vault_root());
        cmd.env("LITERATURE_VAULT_ROOT", vault_root());
        // Match run_script's PATH treatment so Finder-launched builds
        // find /opt/homebrew/bin/uv etc.
        cmd.env("PATH", &enriched);
        cmd.stdin(std::process::Stdio::piped());
        cmd.stdout(std::process::Stdio::piped());
        cmd.stderr(std::process::Stdio::piped());
        match cmd.spawn() {
            Ok(mut child) => {
                use std::io::Write;
                if let Some(stdin) = child.stdin.as_mut() {
                    let _ = stdin.write_all(bibtex.as_bytes());
                }
                Some(child.wait_with_output())
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => None,
            Err(e) => Some(Err(e)),
        }
    };
    let output = try_run("uv", &["run"])
        .or_else(|| try_run("python3", &[]))
        .or_else(|| try_run("python", &[]))
        .ok_or_else(|| "neither `uv` nor `python3` found on PATH".to_string())?
        .map_err(|e| format!("manual_file.py spawn: {e}"))?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);

    if !output.status.success() && output.status.code() != Some(1) {
        return Ok(FilingOutcome {
            inbox_path: path,
            status: FilingStatus::Error,
            citekey: None,
            title: None,
            detail: Some(format!(
                "manual_file.py exited {}: {}",
                output.status.code().unwrap_or(-1),
                stderr.trim()
            )),
        });
    }

    let parsed: FilePaperOut = serde_json::from_str(stdout.trim())
        .map_err(|e| format!("parse manual_file output: {e} — raw: {stdout}"))?;

    if parsed.duplicate {
        return Ok(FilingOutcome {
            inbox_path: path,
            status: FilingStatus::Duplicate,
            citekey: parsed.existing_citekey,
            title: None,
            detail: Some("matched existing entry".into()),
        });
    }

    Ok(FilingOutcome {
        inbox_path: path,
        status: FilingStatus::Filed,
        citekey: parsed.citekey,
        title: None,
        detail: None,
    })
}

pub fn drop_and_file_impl(pdf_paths: Vec<String>) -> Result<Vec<FilingOutcome>> {
    let inbox = ensure_inbox()?;
    let mut results = Vec::with_capacity(pdf_paths.len());
    for p in pdf_paths {
        let src = PathBuf::from(&p);
        if !src.is_file() {
            results.push(FilingOutcome {
                inbox_path: p,
                status: FilingStatus::Error,
                citekey: None,
                title: None,
                detail: Some("not a file".into()),
            });
            continue;
        }
        let dest = match copy_unique_into_inbox(&src, &inbox) {
            Ok(d) => d,
            Err(e) => {
                results.push(FilingOutcome {
                    inbox_path: p,
                    status: FilingStatus::Error,
                    citekey: None,
                    title: None,
                    detail: Some(format!("copy into inbox: {e}")),
                });
                continue;
            }
        };
        results.push(auto_file_one(&dest));
    }
    Ok(results)
}

#[tauri::command]
pub fn drop_and_file(pdf_paths: Vec<String>) -> Result<Vec<FilingOutcome>, String> {
    drop_and_file_impl(pdf_paths).map_err(|e| format!("{e:#}"))
}

/* ---------- viewing the Inbox -------------------------------------------- */

/// Read-only summary of one PDF currently sitting in the Inbox.
/// The frontend uses this to render the Inbox view in the organize mode —
/// retry-filing button, delete, preview the raw PDF.
#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct InboxItem {
    pub path: String,
    pub filename: String,
    pub size_bytes: u64,
    /// ISO-8601 last-modified timestamp (UTC seconds since epoch
    /// formatted as `YYYY-MM-DDTHH:MM:SSZ`). May be empty if the file
    /// system doesn't report a useful mtime.
    pub modified_at: String,
}

fn iso_from_modified(meta: &std::fs::Metadata) -> String {
    let modified = match meta.modified() {
        Ok(t) => t,
        Err(_) => return String::new(),
    };
    let secs = match modified.duration_since(std::time::UNIX_EPOCH) {
        Ok(d) => d.as_secs() as i64,
        Err(_) => return String::new(),
    };
    /* Render UTC without pulling in chrono — a small, stable helper. */
    let days = secs.div_euclid(86_400);
    let time = secs.rem_euclid(86_400);
    let (h, rem) = (time / 3600, time % 3600);
    let (m, s) = (rem / 60, rem % 60);
    /* Civil-from-days algorithm (Howard Hinnant). */
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m_civil = if mp < 10 { mp + 3 } else { mp - 9 };
    let y_civil = if m_civil <= 2 { y + 1 } else { y };
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z",
        y_civil, m_civil, d, h, m, s
    )
}

pub fn list_inbox_impl() -> Result<Vec<InboxItem>> {
    let dir = inbox_dir();
    if !dir.is_dir() {
        return Ok(Vec::new());
    }
    let mut items = Vec::new();
    for entry in std::fs::read_dir(&dir)
        .with_context(|| format!("read_dir {}", dir.display()))?
    {
        let entry = match entry { Ok(e) => e, Err(_) => continue };
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        let filename = match path.file_name().and_then(|f| f.to_str()) {
            Some(f) => f.to_string(),
            None => continue,
        };
        // Skip hidden / temp files (.DS_Store, .inbox-XXXX.tmp from atomic
        // mid-copy, etc.) and require a .pdf extension.
        if filename.starts_with('.') {
            continue;
        }
        if !filename.to_ascii_lowercase().ends_with(".pdf") {
            continue;
        }
        let meta = match entry.metadata() {
            Ok(m) => m,
            Err(_) => continue,
        };
        items.push(InboxItem {
            path: path.to_string_lossy().into_owned(),
            filename,
            size_bytes: meta.len(),
            modified_at: iso_from_modified(&meta),
        });
    }
    // Sort newest-modified first so a freshly-dropped PDF sits on top.
    items.sort_by(|a, b| b.modified_at.cmp(&a.modified_at));
    Ok(items)
}

#[tauri::command]
pub fn list_inbox() -> Result<Vec<InboxItem>, String> {
    list_inbox_impl().map_err(|e| format!("{e:#}"))
}

/// Re-run the filing pipeline on a PDF that's currently in the Inbox.
/// Same logic as the drop-and-file path but with the PDF already in
/// place; useful for "I added a DOI by renaming, try again" or for the
/// case where the scripts were installed after the initial drop.
#[tauri::command]
pub fn inbox_retry_file(path: String) -> Result<FilingOutcome, String> {
    let pdf = PathBuf::from(&path);
    if !pdf.is_file() {
        return Err(format!("not a file: {path}"));
    }
    Ok(auto_file_one(&pdf))
}

/// Remove a PDF from the Inbox. Used when the user decides a dropped
/// file isn't worth keeping (wrong file, garbage, etc.). Errors if the
/// path resolves outside the Inbox directory — protection against a
/// frontend bug passing a path elsewhere in the vault.
#[tauri::command]
pub fn inbox_delete(path: String) -> Result<(), String> {
    let pdf = PathBuf::from(&path);
    let inbox = inbox_dir();
    let inbox_canon = inbox
        .canonicalize()
        .map_err(|e| format!("canonicalize inbox: {e}"))?;
    let pdf_canon = pdf
        .canonicalize()
        .map_err(|e| format!("canonicalize {path}: {e}"))?;
    if !pdf_canon.starts_with(&inbox_canon) {
        return Err(format!(
            "refusing to delete: {} is outside Inbox {}",
            pdf_canon.display(),
            inbox_canon.display(),
        ));
    }
    std::fs::remove_file(&pdf_canon).map_err(|e| format!("remove_file: {e}"))?;
    Ok(())
}

//! Export an annotated PDF (original PDF + stamped numbered badges +
//! appendix pages with the note and an itemised annotation list).
//!
//! Implemented by `scripts/export_annotated_pdf.py`; we just shell out
//! to it via the existing `inbox::run_script` helper and parse the
//! result JSON.

use crate::inbox::{run_script, scripts_dir};
use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExportResult {
    pub output: String,
    pub annotations: u32,
    #[serde(default)]
    pub appendix_pages: u32,
}

/// Build `{citekey}_annotated.pdf` next to the original. Returns the
/// absolute output path the viewer can hand to the OS to preview /
/// reveal. The script handles everything — we just glue.
#[tauri::command]
pub async fn export_annotated_pdf(citekey: String) -> Result<ExportResult, String> {
    if !scripts_dir().join("export_annotated_pdf.py").is_file() {
        return Err("scripts/export_annotated_pdf.py not found in vault".into());
    }
    let citekey_owned = citekey.clone();
    let raw = tokio::task::spawn_blocking(move || {
        run_script("export_annotated_pdf.py", &["--citekey", &citekey_owned])
            .map_err(|e| format!("export_annotated_pdf: {e:#}"))
    })
    .await
    .map_err(|e| format!("export join error: {e}"))??;
    serde_json::from_str(raw.trim())
        .map_err(|e| format!("parse export output: {e} — raw: {raw}"))
}

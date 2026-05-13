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
    pub mode: String,
    #[serde(default)]
    pub cover_pages: u32,
    #[serde(default)]
    pub annotated_pages: u32,
    #[serde(default)]
    pub appendix_pages: u32,
}

/// Build an annotated PDF for `citekey`. `out` is optional: when the
/// viewer's "Export PDF" button opens a save-file dialog and the user
/// picks a destination, that path is passed through; for scripted /
/// agent runs (no `out`) the script falls back to its default
/// (`PDFs/annotation_outputs/{citekey}_annotated.pdf`). `mode` picks
/// the layout — "appendix" (default) or "margin"; see the script's
/// --mode docs for details. Returns the absolute output path so the
/// caller can surface it in the UI.
#[tauri::command]
pub async fn export_annotated_pdf(
    citekey: String,
    out: Option<String>,
    mode: Option<String>,
) -> Result<ExportResult, String> {
    if !scripts_dir().join("export_annotated_pdf.py").is_file() {
        return Err("scripts/export_annotated_pdf.py not found in vault".into());
    }
    let citekey_owned = citekey.clone();
    let raw = tokio::task::spawn_blocking(move || {
        let mut args: Vec<&str> = vec!["--citekey", &citekey_owned];
        if let Some(path) = out.as_deref() {
            args.push("--out");
            args.push(path);
        }
        if let Some(m) = mode.as_deref() {
            args.push("--mode");
            args.push(m);
        }
        run_script("export_annotated_pdf.py", &args)
            .map_err(|e| format!("export_annotated_pdf: {e:#}"))
    })
    .await
    .map_err(|e| format!("export join error: {e}"))??;
    serde_json::from_str(raw.trim())
        .map_err(|e| format!("parse export output: {e} — raw: {raw}"))
}

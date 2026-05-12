use std::sync::mpsc;
use std::time::Duration;

use anyhow::{Context, Result};
use notify::RecursiveMode;
use notify_debouncer_mini::{new_debouncer, DebounceEventResult, Debouncer};
use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager};

use crate::vault::{index_json, paper_notes_dir, vault_root};

/// Held by Tauri's managed state so the debouncer thread stays alive for the
/// lifetime of the app. Dropping it stops the watcher.
pub struct IndexWatcher {
    _debouncer: Debouncer<notify::RecommendedWatcher>,
}

#[derive(Debug, Clone, Serialize)]
struct NoteChanged {
    citekey: String,
}

/// Spawn a debounced filesystem watcher for `index.json` and `PaperNotes/*.md`.
/// - `library:changed` fires when index.json is touched.
/// - `note:changed` (payload: {citekey}) fires when any note file is touched —
///   the note editor uses this to surface a "file changed on disk" banner.
pub fn start_watcher(app: &AppHandle) -> Result<IndexWatcher> {
    let index_target = index_json();
    let vault = vault_root();
    let notes_dir = paper_notes_dir();
    let handle = app.clone();

    let (tx, rx) = mpsc::channel::<DebounceEventResult>();
    let mut debouncer = new_debouncer(Duration::from_millis(250), move |res| {
        let _ = tx.send(res);
    })
    .context("create debouncer")?;
    debouncer
        .watcher()
        .watch(&vault, RecursiveMode::NonRecursive)
        .with_context(|| format!("watch {}", vault.display()))?;
    if notes_dir.is_dir() {
        debouncer
            .watcher()
            .watch(&notes_dir, RecursiveMode::NonRecursive)
            .with_context(|| format!("watch {}", notes_dir.display()))?;
    }

    std::thread::spawn(move || {
        while let Ok(res) = rx.recv() {
            let Ok(events) = res else { continue };
            let mut library_hit = false;
            let mut notes_hit: Vec<String> = Vec::new();
            for ev in events {
                if ev.path == index_target {
                    library_hit = true;
                } else if ev.path.starts_with(&notes_dir)
                    && ev.path.extension().and_then(|s| s.to_str()) == Some("md")
                {
                    if let Some(citekey) = ev
                        .path
                        .file_stem()
                        .and_then(|s| s.to_str())
                        .map(|s| s.to_string())
                    {
                        if !notes_hit.contains(&citekey) {
                            notes_hit.push(citekey);
                        }
                    }
                }
            }
            if library_hit {
                let _ = handle.emit("library:changed", ());
            }
            for citekey in notes_hit {
                let _ = handle.emit("note:changed", NoteChanged { citekey });
            }
        }
    });

    Ok(IndexWatcher {
        _debouncer: debouncer,
    })
}

#[tauri::command]
pub fn start_index_watch(app: AppHandle) -> Result<(), String> {
    if app.try_state::<IndexWatcher>().is_some() {
        return Ok(());
    }
    let watcher = start_watcher(&app).map_err(|e| format!("{e:#}"))?;
    app.manage(watcher);
    Ok(())
}

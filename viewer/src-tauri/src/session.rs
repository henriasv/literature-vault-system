use std::path::PathBuf;

use anyhow::{Context, Result};
use tauri::{AppHandle, Manager};

use crate::atomic::atomic_write;

const SESSION_FILE: &str = "session.json";
const TAB_STATE_DIR: &str = "tab-state";

fn app_data(app: &AppHandle) -> Result<PathBuf> {
    let dir = app
        .path()
        .app_data_dir()
        .context("resolving app data dir")?;
    std::fs::create_dir_all(&dir).with_context(|| format!("create_dir_all {}", dir.display()))?;
    Ok(dir)
}

fn session_path(app: &AppHandle) -> Result<PathBuf> {
    Ok(app_data(app)?.join(SESSION_FILE))
}

fn tab_state_path(app: &AppHandle, citekey: &str) -> Result<PathBuf> {
    let dir = app_data(app)?.join(TAB_STATE_DIR);
    std::fs::create_dir_all(&dir).with_context(|| format!("create_dir_all {}", dir.display()))?;
    // Citekeys are filesystem-safe (validated upstream by the agent), but be defensive.
    let safe: String = citekey
        .chars()
        .filter(|c| c.is_ascii_alphanumeric() || *c == '-' || *c == '_' || *c == '.')
        .collect();
    Ok(dir.join(format!("{safe}.json")))
}

fn read_or_empty(path: &std::path::Path) -> Result<String> {
    if !path.exists() {
        return Ok(String::new());
    }
    std::fs::read_to_string(path).with_context(|| format!("read {}", path.display()))
}

#[tauri::command]
pub fn load_session(app: AppHandle) -> Result<String, String> {
    session_path(&app)
        .and_then(|p| read_or_empty(&p))
        .map_err(|e| format!("{e:#}"))
}

#[tauri::command]
pub fn save_session(app: AppHandle, json: String) -> Result<(), String> {
    (|| -> Result<()> {
        let p = session_path(&app)?;
        atomic_write(&p, json.as_bytes())?;
        Ok(())
    })()
    .map_err(|e| format!("{e:#}"))
}

#[tauri::command]
pub fn load_tab_state(app: AppHandle, citekey: String) -> Result<String, String> {
    tab_state_path(&app, &citekey)
        .and_then(|p| read_or_empty(&p))
        .map_err(|e| format!("{e:#}"))
}

#[tauri::command]
pub fn save_tab_state(app: AppHandle, citekey: String, json: String) -> Result<(), String> {
    (|| -> Result<()> {
        let p = tab_state_path(&app, &citekey)?;
        atomic_write(&p, json.as_bytes())?;
        Ok(())
    })()
    .map_err(|e| format!("{e:#}"))
}

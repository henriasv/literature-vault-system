//! Persistent app settings — currently just the active vault path picked via
//! the File menu. Stored as JSON at `<config_dir>/literature-vault/settings.json`
//! (e.g. `~/Library/Application Support/literature-vault/` on macOS), so it
//! survives across app launches and lives outside the vault itself.

use std::path::PathBuf;

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};

use crate::atomic::atomic_write;

const DIR_NAME: &str = "literature-vault";
const FILE_NAME: &str = "settings.json";

#[derive(Debug, Default, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct Settings {
    pub active_vault: Option<PathBuf>,
}

fn settings_path() -> Result<PathBuf> {
    let base = dirs::config_dir().context("could not determine OS config directory")?;
    Ok(base.join(DIR_NAME).join(FILE_NAME))
}

pub fn load() -> Settings {
    match settings_path() {
        Ok(p) if p.is_file() => std::fs::read_to_string(&p)
            .ok()
            .and_then(|s| serde_json::from_str(&s).ok())
            .unwrap_or_default(),
        _ => Settings::default(),
    }
}

fn save(s: &Settings) -> Result<()> {
    let p = settings_path()?;
    if let Some(parent) = p.parent() {
        std::fs::create_dir_all(parent)
            .with_context(|| format!("mkdir -p {}", parent.display()))?;
    }
    let json = serde_json::to_string_pretty(s)?;
    atomic_write(&p, json.as_bytes())?;
    Ok(())
}

pub fn active_vault() -> Option<PathBuf> {
    load().active_vault
}

pub fn set_active_vault(path: PathBuf) -> Result<()> {
    let mut s = load();
    s.active_vault = Some(path);
    save(&s)
}

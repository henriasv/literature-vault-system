use std::io::Write;
use std::path::Path;

use anyhow::{Context, Result};

pub fn atomic_write(path: &Path, bytes: &[u8]) -> Result<()> {
    let parent = path
        .parent()
        .with_context(|| format!("path has no parent: {}", path.display()))?;
    std::fs::create_dir_all(parent)
        .with_context(|| format!("create_dir_all {}", parent.display()))?;
    let mut tmp = tempfile::Builder::new()
        .prefix(".write-")
        .suffix(".tmp")
        .tempfile_in(parent)
        .with_context(|| format!("tempfile in {}", parent.display()))?;
    tmp.as_file_mut()
        .write_all(bytes)
        .with_context(|| format!("write to tempfile for {}", path.display()))?;
    tmp.as_file_mut()
        .sync_all()
        .with_context(|| format!("fsync tempfile for {}", path.display()))?;
    tmp.persist(path)
        .with_context(|| format!("persist {}", path.display()))?;
    Ok(())
}

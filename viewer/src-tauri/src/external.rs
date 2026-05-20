//! Hand a file off to the OS to open in its default handler (Preview on
//! macOS for PDFs). Used by the right-click "Print…" actions so the user
//! gets a real Preview window with its full print sheet — annotation
//! choice happens before opening, in our app's own dialog.

use std::process::Command;

#[tauri::command]
pub fn open_path_external(path: String) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    let mut cmd = Command::new("open");

    #[cfg(target_os = "linux")]
    let mut cmd = Command::new("xdg-open");

    #[cfg(target_os = "windows")]
    let mut cmd = {
        let mut c = Command::new("cmd");
        c.args(["/C", "start", ""]);
        c
    };

    cmd.arg(&path)
        .spawn()
        .map_err(|e| format!("open external {path}: {e}"))?;
    Ok(())
}

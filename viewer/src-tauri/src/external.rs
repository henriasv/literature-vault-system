//! Two helpers the frontend leans on:
//!
//!  - `open_path_external` hands a file off to the OS default handler
//!    (Preview/Acrobat/etc).
//!  - `print_pdf` shows the native macOS print sheet for a given PDF
//!    using PDFKit's `printOperationForPrintInfo:scalingMode:autoRotate:`
//!    so we never bounce through Preview.

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

#[cfg(target_os = "macos")]
#[tauri::command]
pub fn print_pdf(path: String) -> Result<(), String> {
    use objc2::rc::Retained;
    use objc2::AllocAnyThread;
    use objc2_app_kit::NSPrintInfo;
    use objc2_foundation::{MainThreadMarker, NSString, NSURL};
    use objc2_pdf_kit::{PDFDocument, PDFPrintScalingMode};

    let mtm = MainThreadMarker::new()
        .ok_or_else(|| "print_pdf must run on the main thread".to_string())?;

    /* SAFETY: the calls below are FFI to AppKit / PDFKit which have well-
     * known semantics; the URL is built from a Rust-owned path and the
     * document is dropped before we return. NSPrintOperation.runOperation
     * is synchronous and runs its own modal panel — we only return once
     * the user dismisses the sheet. */
    unsafe {
        let path_ns = NSString::from_str(&path);
        let url: Retained<NSURL> = NSURL::fileURLWithPath(&path_ns);
        let alloc = PDFDocument::alloc();
        let doc = PDFDocument::initWithURL(alloc, &url)
            .ok_or_else(|| format!("PDFDocument: could not open {path}"))?;
        let info = NSPrintInfo::sharedPrintInfo();
        let op = doc
            .printOperationForPrintInfo_scalingMode_autoRotate(
                Some(&info),
                PDFPrintScalingMode::PageScaleToFit,
                true,
                mtm,
            )
            .ok_or_else(|| "PDFDocument: failed to build print operation".to_string())?;
        op.runOperation();
    }
    Ok(())
}

/// Stub on non-macOS so the command list compiles cross-platform.
#[cfg(not(target_os = "macos"))]
#[tauri::command]
pub fn print_pdf(_path: String) -> Result<(), String> {
    Err("print_pdf is only implemented on macOS".into())
}

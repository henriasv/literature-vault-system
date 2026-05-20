mod atomic;
mod collections;
mod export;
mod external;
mod frontmatter;
mod inbox;
mod index;
mod search;
mod session;
mod settings;
mod vault;

/// Register sqlite-vec as a SQLite auto-extension so every connection opened by
/// rusqlite picks it up. Must happen before any Connection::open call.
fn register_sqlite_vec() {
    use rusqlite::ffi::sqlite3_auto_extension;
    use sqlite_vec::sqlite3_vec_init;
    // The transmute layout matches sqlite-vec's own test in their crate; the
    // declared `sqlite3_vec_init` has a stub signature, so we cast through
    // `*const ()` to satisfy `sqlite3_auto_extension`.
    unsafe {
        sqlite3_auto_extension(Some(std::mem::transmute::<
            *const (),
            unsafe extern "C" fn(
                *mut rusqlite::ffi::sqlite3,
                *mut *const std::os::raw::c_char,
                *const rusqlite::ffi::sqlite3_api_routines,
            ) -> std::os::raw::c_int,
        >(sqlite3_vec_init as *const ())));
    }
}

/// Build the macOS menu. Crucially we keep the Window submenu *minimal* —
/// AppKit will auto-populate Move & Resize / Tile / Center / Return-to-
/// Previous-Size items, and bind them to whatever the user has set under
/// System Settings → Keyboard Shortcuts → Windows, AS LONG AS the submenu
/// has been designated the application's windowsMenu via [NSApp setWindowsMenu:].
/// Tauri/muda doesn't do that for us — we do it ourselves in
/// `designate_windows_menu` below.
#[cfg(target_os = "macos")]
fn build_menu(app: &tauri::AppHandle) -> tauri::Result<tauri::menu::Menu<tauri::Wry>> {
    use tauri::menu::{MenuBuilder, MenuItemBuilder, PredefinedMenuItem, SubmenuBuilder};

    let app_submenu = SubmenuBuilder::new(app, "Literature Vault")
        .item(&PredefinedMenuItem::about(app, None, None)?)
        .separator()
        .item(&PredefinedMenuItem::hide(app, None)?)
        .item(&PredefinedMenuItem::hide_others(app, None)?)
        .item(&PredefinedMenuItem::show_all(app, None)?)
        .separator()
        .item(&PredefinedMenuItem::quit(app, None)?)
        .build()?;
    /* File submenu — vault selection. The handlers don't live here; we just
     * tag each item with an id and emit a frontend event in on_menu_event. The
     * Svelte side opens the folder picker, prompts for the optional PDFs
     * symlink (new-vault flow), and calls the Rust commands that actually
     * persist + reload. Keeps this file ignorant of vault-bootstrap details. */
    let open_vault = MenuItemBuilder::with_id("file.open_vault", "Open Vault…")
        .build(app)?;
    let new_vault = MenuItemBuilder::with_id("file.new_vault", "New Vault…")
        .build(app)?;
    /* Print items — operate on the currently active tab's PDF. ⌘P prints the
     * raw PDF; ⌘⇧P generates an annotated copy (using the user's persisted
     * Export PDF mode) and prints that. The actual work happens in the
     * frontend so we just emit events here. */
    let print_pdf = MenuItemBuilder::with_id("file.print_pdf", "Print PDF…")
        .accelerator("CmdOrCtrl+P")
        .build(app)?;
    let print_annotated = MenuItemBuilder::with_id("file.print_annotated", "Print with Annotations…")
        .accelerator("CmdOrCtrl+Shift+P")
        .build(app)?;
    let file_submenu = SubmenuBuilder::new(app, "File")
        .item(&open_vault)
        .item(&new_vault)
        .separator()
        .item(&print_pdf)
        .item(&print_annotated)
        .build()?;
    let edit_submenu = SubmenuBuilder::new(app, "Edit")
        .item(&PredefinedMenuItem::undo(app, None)?)
        .item(&PredefinedMenuItem::redo(app, None)?)
        .separator()
        .item(&PredefinedMenuItem::cut(app, None)?)
        .item(&PredefinedMenuItem::copy(app, None)?)
        .item(&PredefinedMenuItem::paste(app, None)?)
        .item(&PredefinedMenuItem::select_all(app, None)?)
        .build()?;
    let window_submenu = SubmenuBuilder::new(app, "Window")
        .item(&PredefinedMenuItem::minimize(app, None)?)
        .item(&PredefinedMenuItem::maximize(app, None)?)
        .separator()
        .item(&PredefinedMenuItem::bring_all_to_front(app, None)?)
        .build()?;

    MenuBuilder::new(app)
        .items(&[&app_submenu, &file_submenu, &edit_submenu, &window_submenu])
        .build()
}

/// Resize the focused window to mimic Sequoia's Windows-shortcut actions.
/// Used by both the menu (when AppKit's auto-installed item fires) and by the
/// frontend keydown fallback (when WKWebView eats the keystroke before
/// performKeyEquivalent: gets a chance — Ctrl-M → insertNewline: in
/// contenteditable, arrow keys → scroll in overflow containers).
#[cfg(target_os = "macos")]
fn apply_window_action(window: &tauri::WebviewWindow, action: &str) {
    use tauri::{LogicalPosition, LogicalSize};

    if action == "window.zoom" {
        let _ = window.set_resizable(true);
        let _ = window.maximize();
        return;
    }
    let monitor = match window.current_monitor() {
        Ok(Some(m)) => m,
        _ => return,
    };
    let scale = monitor.scale_factor();
    let mon_pos = monitor.position();
    let mon_size = monitor.size();
    // 24-logical-px menu-bar fudge. Approximate; notched displays may vary.
    const MENU_BAR_LOGICAL: f64 = 24.0;
    let logical_x = mon_pos.x as f64 / scale;
    let logical_y = mon_pos.y as f64 / scale + MENU_BAR_LOGICAL;
    let logical_w = mon_size.width as f64 / scale;
    let logical_h = mon_size.height as f64 / scale - MENU_BAR_LOGICAL;
    let (x, y, w, h) = match action {
        "window.fill" => (logical_x, logical_y, logical_w, logical_h),
        "window.tile.left" => (logical_x, logical_y, logical_w / 2.0, logical_h),
        "window.tile.right" => (
            logical_x + logical_w / 2.0,
            logical_y,
            logical_w / 2.0,
            logical_h,
        ),
        "window.tile.top" => (logical_x, logical_y, logical_w, logical_h / 2.0),
        "window.tile.bottom" => (
            logical_x,
            logical_y + logical_h / 2.0,
            logical_w,
            logical_h / 2.0,
        ),
        _ => return,
    };
    let _ = window.unmaximize();
    let _ = window.set_position(LogicalPosition::new(x, y));
    let _ = window.set_size(LogicalSize::new(w, h));
}

#[cfg(target_os = "macos")]
#[tauri::command]
fn window_action(window: tauri::WebviewWindow, action: String) -> Result<(), String> {
    apply_window_action(&window, &action);
    Ok(())
}

/// Stub on non-macOS so the command list compiles cross-platform.
#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn window_action(_action: String) -> Result<(), String> {
    Ok(())
}

/// Find the NSMenu-level submenu titled "Window" inside NSApp.mainMenu and call
/// [NSApp setWindowsMenu:] on it. AppKit then auto-installs Move & Resize / Tile /
/// Zoom / Center / Return-to-Previous-Size items into the submenu and binds them
/// to the user's System-Settings shortcuts.
///
/// Must run on the main thread, after the menu has been installed by Tauri/muda.
/// Called from the `setup` callback, which runs on the main thread post-init.
#[cfg(target_os = "macos")]
fn designate_windows_menu() {
    use objc2::msg_send;
    use objc2_app_kit::{NSApplication, NSMenu, NSMenuItem};
    use objc2_foundation::{ns_string, NSString};

    // SAFETY: called on the main thread (setup runs on main thread); all
    // returned objects are short-lived and used while NSApp owns them.
    unsafe {
        // NSApplication.sharedApplication is the canonical accessor.
        let mtm = match objc2::MainThreadMarker::new() {
            Some(m) => m,
            None => {
                eprintln!("designate_windows_menu: not on main thread; skipping");
                return;
            }
        };
        let app = NSApplication::sharedApplication(mtm);
        let main_menu: Option<objc2::rc::Retained<NSMenu>> = msg_send![&app, mainMenu];
        let Some(main_menu) = main_menu else { return };

        let count: isize = msg_send![&main_menu, numberOfItems];
        let target_title = ns_string!("Window");
        for i in 0..count {
            let item: Option<objc2::rc::Retained<NSMenuItem>> =
                msg_send![&main_menu, itemAtIndex: i];
            let Some(item) = item else { continue };
            let submenu: Option<objc2::rc::Retained<NSMenu>> = msg_send![&item, submenu];
            let Some(submenu) = submenu else { continue };
            let title: objc2::rc::Retained<NSString> = msg_send![&submenu, title];
            if title.isEqualToString(target_title) {
                let _: () = msg_send![&app, setWindowsMenu: &*submenu];
                return;
            }
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    register_sqlite_vec();
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .invoke_handler(tauri::generate_handler![
            vault::list_papers,
            vault::paper_meta,
            vault::read_note,
            vault::write_note,
            vault::set_tags,
            vault::read_bibtex,
            vault::pdf_path_for,
            vault::vault_root_path,
            vault::vault_root_display,
            vault::reassign_with_doi,
            vault::reassign_with_bibtex,
            vault::read_annotations,
            vault::write_annotations,
            vault::is_vault_configured,
            vault::pick_vault,
            vault::create_vault,
            vault::list_review_projects,
            vault::list_review_papers,
            vault::create_review_project,
            vault::update_review_meta,
            inbox::drop_to_inbox,
            inbox::drop_to_review_project,
            inbox::drop_and_file,
            inbox::list_inbox,
            inbox::inbox_retry_file,
            inbox::inbox_delete,
            inbox::search_crossref,
            inbox::inbox_file_with_doi,
            inbox::inbox_file_with_bibtex,
            inbox::inbox_extract_bibtex_stub,
            inbox::fetch_crossref_record,
            inbox::extract_ids_from_pdf,
            export::export_annotated_pdf,
            external::open_path_external,
            external::print_pdf,
            session::load_session,
            session::save_session,
            session::load_tab_state,
            session::save_tab_state,
            index::start_index_watch,
            search::embed_server_health,
            search::search_semantic,
            collections::list_collections,
            collections::collection_add,
            collections::collection_remove,
            collections::collection_create,
            collections::collection_delete,
            collections::collection_rename,
            window_action,
        ]);

    #[cfg(target_os = "macos")]
    let builder = builder
        .menu(|app| build_menu(app))
        .on_menu_event(|app, event| {
            use tauri::Emitter;
            match event.id().as_ref() {
                // File submenu — vault selection. Frontend opens the picker.
                "file.open_vault" => {
                    let _ = app.emit("menu:open-vault", ());
                }
                "file.new_vault" => {
                    let _ = app.emit("menu:new-vault", ());
                }
                "file.print_pdf" => {
                    let _ = app.emit("menu:print-pdf", ());
                }
                "file.print_annotated" => {
                    let _ = app.emit("menu:print-annotated", ());
                }
                _ => {}
            }
        })
        .setup(|_app| {
            designate_windows_menu();
            Ok(())
        });

    builder
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

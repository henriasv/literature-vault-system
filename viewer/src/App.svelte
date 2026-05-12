<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { getCurrentWebview } from "@tauri-apps/api/webview";
  import { open as openFileDialog, confirm as askDialog } from "@tauri-apps/plugin-dialog";
  import { listen, type UnlistenFn } from "@tauri-apps/api/event";
  import { invoke } from "@tauri-apps/api/core";
  import { refreshLibrary, probeEmbedServer } from "./state/library.svelte";
  import { refreshCollections } from "./state/collections.svelte";
  import { dndState, setHoverSlug } from "./state/dnd.svelte";
  import { bootstrapSession, setupAutoSave } from "./state/session.svelte";
  import { startIndexWatch, windowAction } from "./lib/vault";
  import {
    tabsState,
    closeActiveTab,
    closeAllTabs,
    cycleTab,
    jumpToTab,
    requestSearchFocus,
    requestPdfFindFocus,
  } from "./state/tabs.svelte";
  import { prefsState, toggleLibrary } from "./state/prefs.svelte";
  import { dropAndFile, type FilingOutcome } from "./lib/vault";
  import { toast } from "./state/toast.svelte";
  import { makeKeymap } from "./lib/keymap";
  import Library from "./panes/Library.svelte";
  import CollectionsPanel from "./panes/CollectionsPanel.svelte";
  import TabBar from "./panes/TabBar.svelte";
  import TabContent from "./panes/TabContent.svelte";
  import Toaster from "./panes/Toaster.svelte";
  import NoVault from "./panes/NoVault.svelte";
  import ContextMenu from "./panes/ContextMenu.svelte";
  import ReidentifyModal from "./panes/ReidentifyModal.svelte";
  import { reidentifyState } from "./state/reidentify.svelte";

  /**
   * Report the result of a drop-and-file batch. Each PDF goes through
   * the same deterministic Python pipeline the agent uses
   * (`scripts/extract_ids.py` → `scripts/file_paper.py`), so toasts
   * surface the canonical citekey on success and the specific reason
   * on failure (no DOI, duplicate, missing scripts, etc.).
   */
  function toastFilingResults(results: FilingOutcome[]): void {
    if (results.length === 0) return;
    const filed = results.filter((r) => r.status === "filed");
    const duplicate = results.filter((r) => r.status === "duplicate");
    const noId = results.filter((r) => r.status === "no-identifier");
    const errors = results.filter((r) => r.status === "error");
    const noScripts = results.filter((r) => r.status === "scripts-missing");
    const parts: string[] = [];
    if (filed.length > 0) {
      const cks = filed.map((r) => r.citekey).filter(Boolean).join(", ");
      parts.push(`filed ${filed.length}${cks ? ` (${cks})` : ""}`);
    }
    if (duplicate.length > 0) parts.push(`${duplicate.length} already in vault`);
    if (noId.length > 0) parts.push(`${noId.length} without DOI/arXiv (left in Inbox)`);
    if (errors.length > 0) parts.push(`${errors.length} failed`);
    const msg = parts.join(" · ");
    if (noScripts.length > 0) {
      toast(
        `Dropped ${results.length} file${results.length === 1 ? "" : "s"} into Inbox. ` +
          `Auto-filing is unavailable in this vault — install the agent's scripts ` +
          `(extract_ids.py, file_paper.py) under scripts/ to enable.`,
        "error",
      );
      return;
    }
    if (errors.length > 0 || noId.length > 0) {
      toast(msg || "No PDFs processed.", "error");
    } else {
      toast(msg || "No PDFs processed.");
    }
    // Print per-file detail to the devtools console for debugging.
    for (const r of results) {
      if (r.status !== "filed") console.warn(`[file] ${r.inboxPath}: ${r.status}`, r.detail);
    }
  }

  async function addPaperFlow() {
    try {
      const selected = await openFileDialog({
        multiple: true,
        filters: [{ name: "PDF", extensions: ["pdf"] }],
      });
      if (!selected) return;
      const paths = Array.isArray(selected) ? selected : [selected];
      if (paths.length === 0) return;
      const results = await dropAndFile(paths);
      toastFilingResults(results);
    } catch (e) {
      toast(`Add paper failed: ${e}`, "error");
    }
  }

  const dispatch = makeKeymap({
    "Mod+T": { run: requestSearchFocus, allowInEditableTargets: true },
    "Mod+O": { run: requestSearchFocus, allowInEditableTargets: true },
    "Mod+W": { run: closeActiveTab, allowInEditableTargets: true },
    "Mod+Shift+W": { run: closeAllTabs, allowInEditableTargets: true },
    "Mod+\\": { run: toggleLibrary, allowInEditableTargets: true },
    "Mod+Alt+ArrowRight": { run: () => cycleTab(1), allowInEditableTargets: true },
    "Mod+Alt+ArrowLeft": { run: () => cycleTab(-1), allowInEditableTargets: true },
    "Mod+1": { run: () => jumpToTab(1), allowInEditableTargets: true },
    "Mod+2": { run: () => jumpToTab(2), allowInEditableTargets: true },
    "Mod+3": { run: () => jumpToTab(3), allowInEditableTargets: true },
    "Mod+4": { run: () => jumpToTab(4), allowInEditableTargets: true },
    "Mod+5": { run: () => jumpToTab(5), allowInEditableTargets: true },
    "Mod+6": { run: () => jumpToTab(6), allowInEditableTargets: true },
    "Mod+7": { run: () => jumpToTab(7), allowInEditableTargets: true },
    "Mod+8": { run: () => jumpToTab(8), allowInEditableTargets: true },
    "Mod+9": { run: () => jumpToTab(9), allowInEditableTargets: true },
    "Mod+N": { run: () => void addPaperFlow(), allowInEditableTargets: true },
    /* ⌘⇧L — toggle the collections side panel. */
    "Mod+Shift+L": {
      run: () => (prefsState.collectionsPanelOpen = !prefsState.collectionsPanelOpen),
      allowInEditableTargets: true,
    },
    /* ⌘F — context-aware find. When CodeMirror has focus, CM's own
       searchKeymap handles Mod+f and this binding is skipped (default
       allowInEditableTargets: false). When focus is on the body / PDF /
       library, this opens the PDF find panel. ⌘⇧F is a hard escape that
       always opens PDF find, even from inside the editor. */
    "Mod+F": { run: requestPdfFindFocus },
    "Mod+Shift+F": { run: requestPdfFindFocus, allowInEditableTargets: true },
    "/": { run: requestSearchFocus },
  });

  function onKeyDown(e: KeyboardEvent) {
    dispatch(e);
  }

  /**
   * Intercept Sequoia's Window-section shortcuts at the capture phase before
   * WKWebView's per-context defaults fire (Ctrl-M → insertNewline: in
   * contenteditable; arrow keys → scroll in overflow containers). When AppKit's
   * auto-installed menu accelerator catches the event in performKeyEquivalent:,
   * the keystroke is consumed before reaching JS — so this handler only fires
   * in contexts where the menu didn't catch (and our resize would otherwise be
   * eaten by the webview default).
   */
  function onWindowShortcutCapture(e: KeyboardEvent) {
    if (!e.ctrlKey || !e.altKey || e.metaKey || e.shiftKey) return;
    let action: string | null = null;
    switch (e.code) {
      case "KeyM": action = "window.fill"; break;
      case "KeyZ": action = "window.zoom"; break;
      case "ArrowLeft": action = "window.tile.left"; break;
      case "ArrowRight": action = "window.tile.right"; break;
      case "ArrowUp": action = "window.tile.top"; break;
      case "ArrowDown": action = "window.tile.bottom"; break;
    }
    if (!action) return;
    e.preventDefault();
    e.stopPropagation();
    void windowAction(action);
  }

  let dragOver = $state(false);
  let unlistenDragDrop: (() => void) | null = null;

  /**
   * Tauri's OS-level drag handler fires for EVERY drag in the window,
   * including internal HTML5 drags between DOM elements. The HTML5
   * `ondragover`/`ondrop` handlers on our tree nodes never get a chance
   * to fire because WKWebView routes the gesture through the OS layer
   * before the DOM sees it. So this listener does double-duty:
   *
   *   - External file drags (paths populated) → light up the
   *     "Drop PDFs to Inbox" overlay and process the drop into Inbox.
   *   - Internal drags (paths empty, dndState.active === true) →
   *     translate the OS-reported cursor position into a DOM element
   *     via document.elementFromPoint, walk up to a node tagged
   *     `data-drop-target-slug=…`, and either highlight it (over) or
   *     execute the drop into that collection (drop).
   *
   * We decide which branch we're in at `enter` and remember it for the
   * rest of the sequence — Tauri's `over` event has no `paths` field,
   * so we can't re-check mid-drag.
   */
  let lastEnterHadPaths = $state(false);

  /** Find the collection slug, if any, of the element under the given
   *  Tauri-reported drag position.
   *
   *  History: Tauri 2's docs call the field `PhysicalPosition` and
   *  imply physical pixels, but in this build it actually arrives in
   *  logical (CSS) pixels — same units `document.elementFromPoint`
   *  expects. Dividing by devicePixelRatio was producing a
   *  half-position offset on Retina (highlight landed ~one list-length
   *  above the cursor). Use the position as-is. */
  function dropSlugAt(pos: { x: number; y: number }): string | null {
    const el = document.elementFromPoint(pos.x, pos.y) as HTMLElement | null;
    if (!el) return null;
    const target = el.closest<HTMLElement>("[data-drop-target-slug]");
    return target ? target.getAttribute("data-drop-target-slug") : null;
  }

  async function setupDragDrop() {
    const webview = getCurrentWebview();
    const unlisten = await webview.onDragDropEvent(async (event) => {
      if (event.payload.type === "enter") {
        const paths = event.payload.paths ?? [];
        lastEnterHadPaths = paths.length > 0;
        if (lastEnterHadPaths) {
          dragOver = true;
        } else if (dndState.active) {
          setHoverSlug(dropSlugAt(event.payload.position));
        }
      } else if (event.payload.type === "over") {
        if (lastEnterHadPaths) {
          dragOver = true;
        } else if (dndState.active) {
          setHoverSlug(dropSlugAt(event.payload.position));
        }
      } else if (event.payload.type === "leave") {
        dragOver = false;
        lastEnterHadPaths = false;
        if (dndState.active) setHoverSlug(null);
      } else if (event.payload.type === "drop") {
        dragOver = false;
        const wasFileDrop = lastEnterHadPaths;
        lastEnterHadPaths = false;
        if (wasFileDrop) {
          const paths = (event.payload.paths ?? []).filter((p) => p.toLowerCase().endsWith(".pdf"));
          if (paths.length === 0) {
            toast("No PDFs in dropped files.", "error");
            return;
          }
          try {
            const results = await dropAndFile(paths);
            toastFilingResults(results);
            // After filing, refresh library so the new papers show up.
            void refreshLibrary();
          } catch (e) {
            toast(`Drop failed: ${e}`, "error");
          }
        }
        /* Internal drag drop is intentionally NOT handled here. Tauri's
         * OS handler may or may not fire a "drop" event for purely
         * internal drags (nothing crosses the window boundary), so we
         * execute the collection-add from HTML5 dragend on the source
         * element instead — that fires reliably when the drag ends.
         * dndState.hoverSlug carries the target found by Tauri's "over"
         * events during the drag. */
      }
    });
    unlistenDragDrop = unlisten;
  }

  let stopAutoSave: (() => void) | null = null;
  let unlistenLibraryChanged: UnlistenFn | null = null;
  let unlistenMenuOpenVault: UnlistenFn | null = null;
  let unlistenMenuNewVault: UnlistenFn | null = null;

  /* Active-vault tri-state: null while we're asking the backend on startup,
   * false → render <NoVault /> as the entire window, true → normal app. */
  let vaultConfigured = $state<boolean | null>(null);

  /* File > Open Vault… — pick an existing vault folder, persist as active,
   *                      then reload the window so all state initialises fresh.
   * File > New Vault… — pick a fresh location, optionally a PDFs symlink target,
   *                     scaffold the layout, persist as active, reload.
   * NoVault's two buttons reuse the same handlers. */
  async function handleOpenVault() {
    const selected = await openFileDialog({
      directory: true,
      multiple: false,
      title: "Open vault",
    });
    if (typeof selected !== "string") return;
    try {
      await invoke("pick_vault", { path: selected });
      window.location.reload();
    } catch (e) {
      toast.error(String(e));
    }
  }
  async function handleNewVault() {
    const where = await openFileDialog({
      directory: true,
      multiple: false,
      title: "Where should the new vault live?",
    });
    if (typeof where !== "string") return;
    // The dialog plugin's confirm() supports custom button labels, so the user
    // sees the actual choice rather than parsing OK / Cancel.
    //
    // Returns true if the user clicked "External folder…" (-> follow-up picker
    // for the symlink target), false if "Keep inside vault" (-> regular dir).
    const useExternal = await askDialog(
      "PDFs are typically large and don't belong in a git repo of the vault.\n\n" +
        "• Keep inside vault — PDFs/ is a regular folder under the vault. " +
        "Simplest setup; remember to gitignore PDFs/ if you version-control " +
        "the vault.\n\n" +
        "• External folder — pick a directory elsewhere on disk (typically " +
        "Google Drive, Dropbox, or iCloud). A symlink at <vault>/PDFs/ will " +
        "point at it, so the Viewer and Librarian both see the same files " +
        "without storing them inside the vault.",
      {
        title: "Where should PDFs live?",
        kind: "info",
        okLabel: "External folder…",
        cancelLabel: "Keep inside vault",
      },
    );
    let pdfsTarget: string | null = null;
    if (useExternal) {
      const picked = await openFileDialog({
        directory: true,
        multiple: false,
        title: "External folder for PDFs (must be outside the vault)",
      });
      if (typeof picked === "string") pdfsTarget = picked;
    }
    try {
      await invoke("create_vault", { path: where, pdfsTarget });
      window.location.reload();
    } catch (e) {
      toast.error(String(e));
    }
  }

  onMount(() => {
    void (async () => {
      // Menu listeners are registered regardless of vault state — the user
      // needs File > Open/New Vault to work even on the NoVault landing.
      unlistenMenuOpenVault = await listen("menu:open-vault", () => {
        void handleOpenVault();
      });
      unlistenMenuNewVault = await listen("menu:new-vault", () => {
        void handleNewVault();
      });

      // Gate the heavy startup behind an actual vault. If none, render NoVault
      // and skip session / library / index-watch / embed-probe wiring.
      try {
        vaultConfigured = await invoke<boolean>("is_vault_configured");
      } catch {
        vaultConfigured = false;
      }
      if (!vaultConfigured) return;

      await bootstrapSession();
      stopAutoSave = setupAutoSave();
      await refreshLibrary();

      // After the first library load, start the index watcher and re-fetch on changes.
      try {
        await startIndexWatch();
      } catch (e) {
        console.warn("start_index_watch failed", e);
      }
      unlistenLibraryChanged = await listen("library:changed", () => {
        void refreshLibrary();
        void refreshCollections();
      });
      void refreshCollections();
      // Warm-up: probe the embed server in the background so the semantic
      // toggle has a known state by the time the user reaches for it.
      void probeEmbedServer();
    })();
    void setupDragDrop();
    window.addEventListener("keydown", onKeyDown);
    // Capture phase so we run before any in-DOM handler (CodeMirror's keydown,
    // browser default scroll, etc.) — only matters when AppKit's menu didn't
    // already consume the event at NSApplication.performKeyEquivalent:.
    window.addEventListener("keydown", onWindowShortcutCapture, { capture: true });
  });

  onDestroy(() => {
    window.removeEventListener("keydown", onKeyDown);
    window.removeEventListener("keydown", onWindowShortcutCapture, { capture: true } as EventListenerOptions);
    unlistenDragDrop?.();
    stopAutoSave?.();
    unlistenLibraryChanged?.();
    unlistenMenuOpenVault?.();
    unlistenMenuNewVault?.();
  });
</script>

{#if vaultConfigured === false}
  <NoVault onOpen={handleOpenVault} onNew={handleNewVault} />
{:else if vaultConfigured === true}
  <main
    style="--lib-w: {prefsState.libraryCollapsed ? 0 : prefsState.libraryWidth}px;"
    class:dragover={dragOver}
    class:lib-collapsed={prefsState.libraryCollapsed}
    class:coll-open={prefsState.collectionsPanelOpen}
  >
    {#if !prefsState.libraryCollapsed}
      <div class="lib"><Library /></div>
    {/if}
    <div class="reader">
      <TabBar />
      <TabContent />
    </div>
    {#if prefsState.collectionsPanelOpen}
      <!-- Organize view is a full-window overlay so the same Reading /
           Organizing view-switch lands on the same screen (x, y) in both
           modes — and the library + reader (PDF, CodeMirror) stay mounted
           underneath, so toggling back is instant with no state loss. -->
      <div class="organize-overlay"><CollectionsPanel /></div>
    {/if}
  </main>
{/if}

<!-- Global context menu (right-click → paper actions). Mounted at App root
     so it works the same in Reading and Organizing views. -->
<ContextMenu />

<!-- Re-identify modal for an already-filed paper. Opens from the right-click
     menu's "Re-identify with CrossRef…" item; closes on ✕ / Esc / cancel. -->
{#if reidentifyState.citekey}
  <ReidentifyModal citekey={reidentifyState.citekey} />
{/if}

{#if dragOver}
  <div class="drop-overlay">
    <div class="drop-card">Drop PDFs to add to Inbox</div>
  </div>
{/if}

<Toaster />

<style>
  main {
    display: grid;
    grid-template-columns: var(--lib-w) 1fr;
    column-gap: 0;
    height: 100vh;
    background: var(--recess);
    position: relative;
  }
  .organize-overlay {
    position: absolute;
    inset: 0;
    z-index: 20;
    background: var(--backdrop);
  }
  main.lib-collapsed {
    grid-template-columns: 1fr;
  }
  .lib {
    grid-column: 1;
    border-right: 1px solid var(--ink-12);
    min-width: 0;
    overflow: hidden;
    background: var(--surface);
  }
  main.lib-collapsed .lib {
    display: none;
  }
  .reader {
    grid-column: 2;
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    background: var(--surface);
    position: relative;
  }
  main.lib-collapsed .reader {
    grid-column: 1;
  }
  .drop-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.4);
    backdrop-filter: blur(2px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 999;
    pointer-events: none;
  }
  .drop-card {
    background: var(--bg);
    color: var(--fg);
    border: 2px dashed var(--accent);
    border-radius: 8px;
    padding: 32px 48px;
    font-size: 14px;
  }
</style>

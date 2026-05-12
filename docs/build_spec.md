# Literature Vault Viewer — Build Spec

## Overview

A Tauri desktop app for reading and editing the existing literature vault at `~/repos/librarian_assistant_vault/`. Replaces the current Obsidian-based reading workflow. Side-by-side PDF + markdown note in tabs, semantic search via the existing embed server, new-paper ingress via the existing agent (drop into `Inbox/`).

The vault data model and filing pipeline are pre-existing and **out of scope to modify**. See `~/repos/librarian_assistant_vault/DESIGN.md` and the Literature Vault Handoff doc for the data model. This spec only describes the viewer.

The viewer is a thin reader/editor on top of a filesystem. The agent is the filer. They share the vault filesystem and nothing else.

---

## Stack

- **Shell**: Tauri 2.x
- **Frontend**: Svelte 5 + TypeScript + Vite
- **State**: Svelte 5 runes (`$state`, `$derived`, `$effect`) in `.svelte.ts` modules. No external state library.
- **Editor**: CodeMirror 6 (`@codemirror/state`, `@codemirror/view`, `@codemirror/lang-markdown`) — mounted directly in a Svelte component, no wrapper library.
- **PDF**: `pdfjs-dist` directly, wrapped in a small Svelte component. No higher-level viewer library.
- **Layout**: `paneforge` for resizable splits.
- **Backend (Rust)**: `serde`, `serde_yaml`, `notify`, `rusqlite` (with `sqlite-vec` extension), `reqwest`, `tokio`.

---

## Repo Layout

```
viewer/
├─ src-tauri/
│  ├─ src/
│  │  ├─ main.rs
│  │  ├─ vault.rs        # paths, list, frontmatter parse, atomic writes
│  │  ├─ index.rs        # index.json read + watch
│  │  ├─ search.rs       # embed server HTTP + sqlite-vec
│  │  ├─ inbox.rs        # drop-to-Inbox filing
│  │  ├─ session.rs      # tab session persistence
│  │  └─ annotations.rs  # xfdf sidecar IO  (v3)
│  ├─ Cargo.toml
│  └─ tauri.conf.json
├─ src/
│  ├─ App.svelte
│  ├─ main.ts
│  ├─ panes/
│  │  ├─ Library.svelte
│  │  ├─ TabBar.svelte
│  │  ├─ TabContent.svelte
│  │  ├─ PDFView.svelte
│  │  └─ NoteEditor.svelte
│  ├─ state/
│  │  ├─ tabs.svelte.ts      # tab session, active index
│  │  ├─ library.svelte.ts   # paper list, filters, search results
│  │  └─ prefs.svelte.ts     # split ratio, library width, recents
│  ├─ lib/
│  │  ├─ vault.ts        # typed wrappers around tauri invokes
│  │  ├─ pdf.ts          # pdfjs-dist setup, worker config
│  │  └─ keymap.ts
│  └─ styles/
└─ package.json
```

State modules use `.svelte.ts` so runes work at module scope. Pattern:

```ts
// state/tabs.svelte.ts
import type { Tab } from "../lib/vault";

export const tabsState = $state<{ tabs: Tab[]; activeIndex: number }>({
  tabs: [],
  activeIndex: 0,
});

export function openInNewTab(citekey: string) { /* ... */ }
export function closeTab(idx: number) { /* ... */ }
```

Components import and read/mutate directly. No store boilerplate.

---

## Vault Path Resolution

Single setting: `VAULT_ROOT`, default `~/repos/librarian_assistant_vault`.

```rust
fn note_path(citekey: &str)    -> PathBuf  // PaperNotes/{citekey}.md
fn bib_path(citekey: &str)     -> PathBuf  // Bibfiles/{citekey}.bib
fn pdf_path(citekey: &str)     -> PathBuf  // PDFs/{citekey}.pdf
fn xfdf_path(citekey: &str)    -> PathBuf  // Annotations/{citekey}.xfdf
fn project_path(name: &str)    -> PathBuf  // Projects/{name}.md
fn inbox_dir()                 -> PathBuf  // Inbox/
fn index_json()                -> PathBuf  // index.json
fn embeddings_db()             -> PathBuf  // embeddings.db
```

`Annotations/` is created on demand. Vault is git-tracked; `Annotations/` should be tracked too (annotations are knowledge, not session state).

---

## Data Types

```ts
// src/lib/vault.ts
export interface PaperMeta {
  citekey: string;
  title: string;
  authors: string[];
  authorCount?: number;     // present when authors list was truncated
  year: number;
  journal: string | null;
  doi: string | null;
  arxivId: string | null;
  added: string;            // ISO date
  tags: string[];
  abstract: string | null;
  hasNote: boolean;
  hasPdf: boolean;
}

export interface Tab {
  citekey: string;
  pdfPage: number;
  pdfZoom: number | "auto";
  scrollPos: { pdf: number; note: number };
}

export interface Session {
  tabs: Tab[];
  activeIndex: number;
  splitRatio: number;       // 0..1, global PDF/note split
  libraryCollapsed: boolean;
  libraryWidth: number;     // px
}

export interface SearchHit { citekey: string; score: number }
export interface EmbedServerHealth {
  ok: boolean;
  default: string;
  loaded: string[];
  idleSec: number;
}
```

---

## Tauri Commands (Rust → TS contract)

```rust
// vault.rs
#[tauri::command] fn list_papers() -> Vec<PaperMeta>;
#[tauri::command] fn paper_meta(citekey: String) -> PaperMeta;
#[tauri::command] fn read_note(citekey: String) -> String;
#[tauri::command] fn write_note(citekey: String, contents: String) -> Result<()>;  // atomic

// index.rs
#[tauri::command] fn start_index_watch() -> Result<()>;  // emits "library:changed"

// search.rs
#[tauri::command] fn search_metadata(query: String, limit: u32) -> Vec<PaperMeta>;
#[tauri::command] fn search_semantic(query: String, limit: u32) -> Vec<SearchHit>;
#[tauri::command] fn embed_server_health() -> EmbedServerHealth;

// inbox.rs
#[tauri::command] fn drop_to_inbox(pdf_paths: Vec<String>) -> Vec<String>;  // returns inbox paths

// session.rs
#[tauri::command] fn load_session() -> Session;
#[tauri::command] fn save_session(session: Session) -> Result<()>;

// annotations.rs (v3)
#[tauri::command] fn read_xfdf(citekey: String) -> String;     // "" if absent
#[tauri::command] fn write_xfdf(citekey: String, xfdf: String) -> Result<()>;
```

Wrap all of these in `src/lib/vault.ts` with typed signatures. Components never call `invoke` directly.

All write commands use atomic write: tempfile in same dir + `std::fs::rename`. No partial overwrites, ever.

---

## UI Layout

```
┌──────────┬───────────────────────────────────────────┐
│          │ [Juel 2025 ×] [Aczel 2026 ×] [+]          │
│ Library  ├───────────────────────────────────────────┤
│          │                    │                      │
│ search   │                    │                      │
│ ────     │                    │                      │
│ All      │     PDF view       │    Note editor       │
│ Recent   │                    │                      │
│ ────     │  pdfjs-dist        │    CodeMirror 6      │
│ Tags     │  (Svelte wrapper)  │    (whole .md file)  │
│  mlip    │                    │                      │
│  ice…    │                    │                      │
│ ────     │                    │                      │
│ Manus-   │                    │                      │
│ cripts   │                    │                      │
│ thesis-3 │                    │                      │
│ helfo-r  │                    │                      │
└──────────┴────────────────────┴──────────────────────┘
   280px              flex 50%        flex 50%
   collapsible        paneforge divider (global ratio)
```

### Library pane (`Library.svelte`)

- Top: search input. Two modes (toggle): metadata (instant, in-memory) or semantic (embed server). Toggle visible, default metadata.
- Sections (sidebar nav):
  - **All papers** — list, sortable by `added` (default), `year`, `journal`, `title`.
  - **Recent** — last N opened, persisted in app data dir.
  - **Tags** — flat list of all topic tags. Click filters. Multi-select with cmd-click.
  - **Manuscripts** — first-class section for `cite:*` tags. Click → filter library to papers tagged with that. This is the killer view.
- Each list row: title (truncate to one line), `{first_author} {year} · {journal}`, tag chips below.
- Plain click → replace current tab.
- ⌘-click or middle-click → open in new tab.
- Width default 280px, drag-resizable, persisted. ⌘\ collapses to icon rail.
- Citekey is **never** shown in the UI; always render derived display strings.

### Tab bar (`TabBar.svelte`)

- Each tab: `{first_author} {year}` derived from frontmatter. Close button.
- ⌘T → new tab; focuses library search.
- ⌘W close current. ⌘⇧W close all.
- ⌘1..⌘9 → jump to tab N.
- ⌘⌥→ / ⌘⌥← → cycle tabs.
- Drag to reorder (deferred to v3 if non-trivial).
- If user opens a paper that's already in a tab → focus that tab, don't duplicate.
- Empty state (no tabs): main area shows "Recently opened" list.

### Tab content (`TabContent.svelte`)

Two panes side-by-side via `paneforge`. Each tab is rendered with `display: none` when inactive so PDF + CodeMirror state survives switching. At ~10 tabs this is comfortable.

**`PDFView.svelte`**: thin wrapper around `pdfjs-dist`.
- Set up the worker in `src/lib/pdf.ts` once at app start (`GlobalWorkerOptions.workerSrc`).
- Component takes a `pdfPath` prop, loads via `getDocument`, renders pages to canvases on demand.
- Toolbar: page nav, zoom (fit-width / fit-page / 50–400% steps), text search via PDF.js's text layer.
- Persist scroll/page/zoom per tab to the per-citekey JSON in app data dir.
- Use `IntersectionObserver` for page virtualization — render only visible pages + 1 above/below.

**`NoteEditor.svelte`**: thin wrapper around CodeMirror 6.
- Single CM6 view over the entire note file.
- Markdown mode, monospace, line wrapping on, no line numbers.
- No section parsing. Full file editable. Trust the user.
- Atomic write (via Tauri `write_note`) on tab blur **or** after 2s of inactivity, whichever comes first.
- Mount CM6 directly in `onMount`; tear down in `onDestroy`. No third-party Svelte wrapper.

Split ratio: **global** preference (single number 0..1) bound to `paneforge`'s controlled API. Drag the divider, persist to session.

---

## Keyboard Shortcuts

| Key | Action |
|---|---|
| `⌘T` | New tab (focus library search) |
| `⌘W` | Close current tab |
| `⌘⇧W` | Close all tabs |
| `⌘1`–`⌘9` | Jump to tab N |
| `⌘⌥→` / `⌘⌥←` | Cycle tabs |
| `⌘\` | Toggle library |
| `/` | Focus library search |
| `⌘F` | Find in current note (CM6 built-in) |
| `⌘⇧F` | Find in PDF |
| `⌘N` | Add paper (file picker → drop to Inbox) |
| `⌘O` | Open paper… (focus library search) |

Implement via a single global `keydown` listener in `App.svelte` that dispatches against the keymap module. Keep CM6 / PDF.js's own keybindings working when they have focus (CM6 ⌘F, etc).

---

## Note Editing

- Single CodeMirror instance. Full file editable. Trust the user.
- Atomic write on tab blur **or** after 2s of inactivity, whichever comes first.
- Pattern: write to `{path}.{nonce}.tmp` in the same directory, then `std::fs::rename` to `{path}`. Atomic on a single FS.
- Reads: plain `fs::read_to_string`. No locking.
- **File-changed-on-disk handling**: subscribe to `notify` events on `PaperNotes/{citekey}.md`. If the file changes while editing (e.g. agent ingest), do NOT auto-overwrite. Show a small banner: "file changed on disk — reload" with a Reload button. The user's in-memory edits are sacred until they explicitly discard them.
- Tab title derivation: `{authors[0].split(', ')[0]} {year}` from frontmatter. Fallback to citekey if frontmatter missing/malformed.

---

## Search

### Metadata (instant)

In-memory filter over the loaded `PaperMeta[]` (held in `state/library.svelte.ts` as `$state`). Substring match across `title`, `authors`, `journal`, `citekey`, `tags`. Updates on every keystroke via `$derived`. Zero remote calls.

### Semantic (embed server)

Toggle in the search input. When active:

1. POST `http://127.0.0.1:5817/embed` with `{texts: [query], prompt: "query"}`. Use the registry default model.
2. Open `embeddings.db` read-only via `rusqlite`. Load the `sqlite-vec` extension. Query nearest-neighbors in `vec_papers__<safe_model_id>` (sanitize the model id per the embed server's convention — replace `-` and `.` with `_`).
3. Return `[{citekey, score}, …]`. Look up `PaperMeta` for each.

**Warm-up**: hit `GET /health` once on app start. If first real query takes >500ms, show subtle "warming…" indicator. Subsequent queries are warm within the 30-min idle window.

**Failure**: if the embed server is unreachable, disable the semantic toggle with a tooltip "embed server unreachable." Never block the app on it.

---

## Adding Papers

**Drop to Inbox.** That's the entire viewer responsibility.

- Drag PDF(s) onto the viewer window → `drop_to_inbox` copies each to `{vault}/Inbox/{original_filename}`.
- If a name collision exists, append a numeric suffix (`paper.pdf` → `paper-1.pdf`).
- Show a single toast: "Dropped N file(s) into Inbox — agent will file shortly."
- The library will auto-refresh once `index.json` updates (via `notify` watcher in `index.rs`). New paper appears in the list, ready to open.
- ⌘N opens a native file picker for the same flow.

**Out of scope for the viewer**: DOI extraction, CrossRef search, dedup logic, embedding refresh. The existing agent owns all of that.

---

## Persistence

UI state lives in **Tauri's app data dir** (`tauri::path::app_data_dir`):

- `session.json` — open tabs, active index, split ratio, library state.
- `tab-state/{citekey}.json` — per-paper PDF page/zoom/scroll.
- `recent.json` — recently opened citekeys.

The vault is **never** written to from the viewer except for:
- `PaperNotes/{citekey}.md` (note edits)
- `Projects/{name}.md` (project note edits)
- `Annotations/{citekey}.xfdf` (v3 only)

UI state is not knowledge. Don't pollute the vault with it.

---

## Constraints (non-negotiable)

- **Atomic writes** for any file in the vault. `.tmp` + rename. Never partial.
- **Never write into `PDFs/`** from the viewer. (PDFs live on a Drive symlink; writes round-trip to cloud.)
- **`embeddings.db` is read-only** from the viewer. The `embed_corpus.py` pipeline owns it.
- **`index.json` and `library.bib` are read-only** from the viewer. The agent owns them.
- **Citekey is permanent.** Never expose a "rename" affordance.
- **Frontmatter required fields** (citekey, title, authors, year, doi, arxiv_id, added, tags, sha256_pdf) must be preserved on note write. If parsing fails, the safe action is to refuse the write and surface an error rather than emit malformed YAML.

---

## Phasing

### v1 — core reading (target: weekend 1)

- [ ] Tauri scaffold, Svelte 5 + Vite frontend, vault path resolution
- [ ] `vault.rs`: `list_papers`, `read_note`, `write_note` (atomic), `paper_meta`
- [ ] `Library.svelte`: list view, sort, metadata search, tag filter
- [ ] `TabBar.svelte`: new/close/cycle/jump
- [ ] `TabContent.svelte` with `PDFView.svelte` (read-only) + `NoteEditor.svelte` (full-file editable)
- [ ] Keyboard shortcuts (core set above)
- [ ] Session persistence; restore on launch
- [ ] Drop-to-Inbox add paper flow (`drop_to_inbox` + drag-drop handler + ⌘N)

### v2 — agent integration & semantic search (weekend 2)

- [ ] `index.rs`: watch `index.json`; emit `library:changed` event; library auto-refresh
- [ ] `search.rs`: semantic search via embed server + sqlite-vec
- [ ] Embed server health check + warm-up indicator
- [ ] Manuscripts (`cite:*`) sidebar section as a first-class browsing axis
- [ ] File-changed-on-disk banner on the note pane
- [ ] Recent papers tracking and view

### v3 — annotations & polish (later)

- [ ] xfdf sidecar read; render annotation overlay on PDF (highlights, notes)
- [ ] xfdf sidecar write on annotation create/edit/delete (atomic)
- [ ] Optional "Bake annotations into PDF" command using `pdf-lib` (one-shot, on demand)
- [ ] Drag tab reorder
- [ ] Multi-PDF batch drop with progress queue

---

## Acceptance — v1

- App launches; library shows all papers from the vault sorted by `added` desc.
- Click a paper → opens in current tab (or a new tab if none). PDF + note both load side-by-side at the global split ratio.
- Edit note → close tab → file is atomic-written, no `.tmp` left behind.
- Reopen app → previous tabs and split ratio restored.
- ⌘1-9 jumps tabs, ⌘W closes, ⌘\ toggles library.
- Tag filter narrows the library list.
- Tab title shows `{first_author} {year}`, never the citekey.
- Drag PDF onto window → file appears in `{vault}/Inbox/`. Library list updates within seconds (manual reload acceptable in v1; auto-refresh is v2).

---

## Notes for the implementing agent

- The vault is real data; develop against `~/repos/librarian_assistant_vault` directly. No fixture set; use what's there. Don't write test data into the vault.
- **Do not reimplement the agent.** The viewer reads the vault and writes only notes (and later xfdf). All filing is the agent's job.
- Refer to the Literature Vault Handoff doc for data model details. This spec references but does not restate it.
- When in doubt about a UX call, prefer "single-paper, single-window, keyboard-first" over feature density.
- The atomic write helper in `vault.rs` is used by every write path — get it right first, reuse everywhere.
- Use `serde_yaml` for frontmatter. Preserve the rest of the file byte-for-byte when writing — only the YAML block and body are touched.
- For the embed server, `safe_model_id` mirrors the script convention: replace `-` and `.` with `_` (e.g. `nemotron-8b` → `nemotron_8b`).
- All filesystem I/O lives in Rust commands invoked via `src/lib/vault.ts`. Components never touch the filesystem directly.
- State lives in `.svelte.ts` modules using runes. No external state library.
- Use Svelte 5 syntax throughout: `$state`, `$derived`, `$effect`, `$props`, `{#snippet}`. Don't use legacy stores (`writable`, `readable`) unless interop with a non-Svelte source actually requires it.
- `pdfjs-dist` worker setup: import the worker bundle in `src/lib/pdf.ts` and set `GlobalWorkerOptions.workerSrc` once. See pdfjs-dist docs for the Vite-specific worker import pattern.
- Prefer small, focused commits. The phasing above is a reasonable commit cadence.
/** Each recent entry remembers WHEN the paper was last opened so the
 *  Library's Recent section can show "5 min ago" / "2 d ago" beside
 *  each title — otherwise users can't tell why something is in the list. */
export interface RecentEntry {
  citekey: string;
  at: number;
}

/** Top-level mode the app is in. "reading" is the default PDF+notes view;
 *  "organize" overlays the CollectionsPanel for library curation;
 *  "review" overlays the Reviewing pane for grading student work
 *  (PDFs in `PDFs/reviewing/<project>/`, notes in `ReviewNotes/<project>/`,
 *  hidden from the main library). All three are mutually exclusive. */
export type ViewMode = "reading" | "organize" | "review";

/** Which tab the NoteEditor shows for the active paper. Lifted into prefs
 *  so the choice persists across paper switches (and reloads) — the
 *  default was reverting to "rendered" every time the user opened a new
 *  tab, which felt clumsy when they wanted to keep editing. */
export type NoteViewMode = "rendered" | "raw" | "annotations";

interface PrefsState {
  splitRatio: number;
  libraryWidth: number;
  libraryCollapsed: boolean;
  viewMode: ViewMode;
  noteViewMode: NoteViewMode;
  collectionsPanelWidth: number;
  recents: RecentEntry[];
  /** Focus / reading mode: hides library, tab bar and collections so
   *  the PDF can take the full height of the window, and re-orients
   *  the PDF toolbar to a vertical strip on the left so the page area
   *  isn't squeezed by a top toolbar. Toggled from the toolbar's FOCUS
   *  button, also flips the Tauri window to fullscreen. */
  focusMode: boolean;
}

const RECENT_LIMIT = 30;

export const prefsState = $state<PrefsState>({
  splitRatio: 0.5,
  libraryWidth: 360,
  libraryCollapsed: false,
  viewMode: "reading",
  noteViewMode: "rendered",
  collectionsPanelWidth: 260,
  recents: [],
  focusMode: false,
});

export function pushRecent(citekey: string): void {
  const without = prefsState.recents.filter((r) => r.citekey !== citekey);
  prefsState.recents = [{ citekey, at: Date.now() }, ...without].slice(0, RECENT_LIMIT);
}

/** Migrate `string[]` from older session.json shape into `RecentEntry[]`. */
export function normalizeRecents(raw: unknown): RecentEntry[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item): RecentEntry | null => {
      if (typeof item === "string") return { citekey: item, at: 0 };
      if (item && typeof item === "object" && "citekey" in item) {
        const c = (item as { citekey: unknown }).citekey;
        const a = (item as { at: unknown }).at;
        if (typeof c === "string") return { citekey: c, at: typeof a === "number" ? a : 0 };
      }
      return null;
    })
    .filter((x): x is RecentEntry => x !== null)
    .slice(0, RECENT_LIMIT);
}

export function toggleLibrary(): void {
  prefsState.libraryCollapsed = !prefsState.libraryCollapsed;
}

/** Toggle focus / reading mode. Also flips the Tauri window to
 *  fullscreen so the OS chrome is hidden along with the app chrome. */
export async function toggleFocusMode(): Promise<void> {
  const next = !prefsState.focusMode;
  prefsState.focusMode = next;
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    await getCurrentWindow().setFullscreen(next);
  } catch (e) {
    /* Non-fatal — the layout still flips even if the window can't
     * enter fullscreen (e.g., outside Tauri or permission denied). */
    console.warn("[focus] setFullscreen failed", e);
  }
}

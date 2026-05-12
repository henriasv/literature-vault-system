/** Each recent entry remembers WHEN the paper was last opened so the
 *  Library's Recent section can show "5 min ago" / "2 d ago" beside
 *  each title — otherwise users can't tell why something is in the list. */
export interface RecentEntry {
  citekey: string;
  at: number;
}

interface PrefsState {
  splitRatio: number;
  libraryWidth: number;
  libraryCollapsed: boolean;
  collectionsPanelOpen: boolean;
  collectionsPanelWidth: number;
  recents: RecentEntry[];
}

const RECENT_LIMIT = 30;

export const prefsState = $state<PrefsState>({
  splitRatio: 0.5,
  libraryWidth: 360,
  libraryCollapsed: false,
  collectionsPanelOpen: false,
  collectionsPanelWidth: 260,
  recents: [],
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

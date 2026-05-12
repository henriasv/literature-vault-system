import {
  loadSessionRaw,
  saveSessionRaw,
  loadTabStateRaw,
  saveTabStateRaw,
  type Session,
  type Tab,
} from "../lib/vault";
import { tabsState } from "./tabs.svelte";
import { prefsState, pushRecent, normalizeRecents, type RecentEntry } from "./prefs.svelte";

interface PersistedSession {
  /** `preview` is optional: sessions written before the preview-tab
   *  feature shipped don't carry it, and on restore those tabs default
   *  to permanent (preview = false). */
  tabs: Array<{ citekey: string; preview?: boolean }>;
  activeIndex: number;
  splitRatio: number;
  libraryCollapsed: boolean;
  libraryWidth: number;
  collectionsPanelOpen: boolean;
  collectionsPanelWidth: number;
  /** May arrive as legacy `string[]` from older session.json — normalized via
   *  `normalizeRecents` on load. */
  recents: RecentEntry[] | string[];
}

interface PersistedTabState {
  pdfPage: number;
  pdfZoom: number | "auto";
  scrollPos: { pdf: number; note: number };
}

const SESSION_DEBOUNCE_MS = 400;
const TAB_STATE_DEBOUNCE_MS = 800;

let sessionTimer: number | null = null;
const tabStateTimers = new Map<string, number>();

let bootstrapped = $state(false);
export function isBootstrapped(): boolean {
  return bootstrapped;
}

function defaultPersistedTabState(): PersistedTabState {
  return { pdfPage: 1, pdfZoom: "auto", scrollPos: { pdf: 0, note: 0 } };
}

export async function loadTabState(citekey: string): Promise<PersistedTabState> {
  try {
    const raw = await loadTabStateRaw(citekey);
    if (!raw) return defaultPersistedTabState();
    const parsed = JSON.parse(raw) as PersistedTabState;
    return {
      pdfPage: typeof parsed.pdfPage === "number" ? parsed.pdfPage : 1,
      pdfZoom: parsed.pdfZoom === "auto" || typeof parsed.pdfZoom === "number" ? parsed.pdfZoom : "auto",
      scrollPos: parsed.scrollPos ?? { pdf: 0, note: 0 },
    };
  } catch {
    return defaultPersistedTabState();
  }
}

export function scheduleTabStateSave(citekey: string): void {
  const existing = tabStateTimers.get(citekey);
  if (existing !== undefined) window.clearTimeout(existing);
  const timer = window.setTimeout(async () => {
    tabStateTimers.delete(citekey);
    const tab = tabsState.tabs.find((t) => t.citekey === citekey);
    if (!tab) return;
    const payload: PersistedTabState = {
      pdfPage: tab.pdfPage,
      pdfZoom: tab.pdfZoom,
      scrollPos: tab.scrollPos,
    };
    try {
      await saveTabStateRaw(citekey, JSON.stringify(payload));
    } catch (e) {
      console.error(`save_tab_state(${citekey}) failed`, e);
    }
  }, TAB_STATE_DEBOUNCE_MS);
  tabStateTimers.set(citekey, timer);
}

/** Force-save the per-paper state immediately (used right before close). */
export async function flushTabState(citekey: string): Promise<void> {
  const existing = tabStateTimers.get(citekey);
  if (existing !== undefined) window.clearTimeout(existing);
  tabStateTimers.delete(citekey);
  const tab = tabsState.tabs.find((t) => t.citekey === citekey);
  if (!tab) return;
  const payload: PersistedTabState = {
    pdfPage: tab.pdfPage,
    pdfZoom: tab.pdfZoom,
    scrollPos: tab.scrollPos,
  };
  try {
    await saveTabStateRaw(citekey, JSON.stringify(payload));
  } catch (e) {
    console.error(`flush_tab_state(${citekey}) failed`, e);
  }
}

export function scheduleSessionSave(): void {
  if (!bootstrapped) return;
  if (sessionTimer !== null) window.clearTimeout(sessionTimer);
  sessionTimer = window.setTimeout(async () => {
    sessionTimer = null;
    const payload: PersistedSession = {
      tabs: tabsState.tabs.map((t) => ({ citekey: t.citekey, preview: t.preview === true })),
      activeIndex: tabsState.activeIndex,
      splitRatio: prefsState.splitRatio,
      libraryCollapsed: prefsState.libraryCollapsed,
      libraryWidth: prefsState.libraryWidth,
      collectionsPanelOpen: prefsState.collectionsPanelOpen,
      collectionsPanelWidth: prefsState.collectionsPanelWidth,
      recents: prefsState.recents,
    };
    try {
      await saveSessionRaw(JSON.stringify(payload));
    } catch (e) {
      console.error("save_session failed", e);
    }
  }, SESSION_DEBOUNCE_MS);
}

export async function bootstrapSession(): Promise<void> {
  try {
    const raw = await loadSessionRaw();
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<PersistedSession>;
      if (typeof parsed.splitRatio === "number") prefsState.splitRatio = parsed.splitRatio;
      if (typeof parsed.libraryCollapsed === "boolean")
        prefsState.libraryCollapsed = parsed.libraryCollapsed;
      if (typeof parsed.libraryWidth === "number") prefsState.libraryWidth = parsed.libraryWidth;
      if (typeof parsed.collectionsPanelOpen === "boolean")
        prefsState.collectionsPanelOpen = parsed.collectionsPanelOpen;
      if (typeof parsed.collectionsPanelWidth === "number")
        prefsState.collectionsPanelWidth = parsed.collectionsPanelWidth;
      if (Array.isArray(parsed.recents)) prefsState.recents = normalizeRecents(parsed.recents);
      if (Array.isArray(parsed.tabs) && parsed.tabs.length > 0) {
        // For each persisted tab, hydrate per-paper PDF state from disk.
        const hydrated: Tab[] = [];
        /* At most one preview tab can be restored; if multiple are
         * persisted (shouldn't happen but be defensive), only the first
         * keeps its preview flag, the rest are promoted to permanent. */
        let previewSeen = false;
        for (const t of parsed.tabs) {
          if (!t || typeof t.citekey !== "string") continue;
          const ts = await loadTabState(t.citekey);
          const isPreview = t.preview === true && !previewSeen;
          if (isPreview) previewSeen = true;
          hydrated.push({
            citekey: t.citekey,
            pdfPage: ts.pdfPage,
            pdfZoom: ts.pdfZoom,
            scrollPos: ts.scrollPos,
            preview: isPreview,
          });
        }
        tabsState.tabs = hydrated;
        tabsState.activeIndex =
          typeof parsed.activeIndex === "number" &&
          parsed.activeIndex >= 0 &&
          parsed.activeIndex < hydrated.length
            ? parsed.activeIndex
            : hydrated.length > 0
              ? 0
              : -1;
      }
    }
  } catch (e) {
    console.error("bootstrap session failed; starting fresh", e);
  } finally {
    bootstrapped = true;
  }
}

/**
 * Wire reactive auto-save: structural session changes write session.json
 * (debounced); per-tab PDF state changes write tab-state/{citekey}.json
 * (debounced separately so a single PDF scroll doesn't churn the session file).
 *
 * Returns a teardown function; on app destroy you can call it.
 */
export function setupAutoSave(): () => void {
  const stop = $effect.root(() => {
    // Session.json: structure (tabs by citekey, active index, prefs).
    $effect(() => {
      void tabsState.activeIndex;
      void prefsState.splitRatio;
      void prefsState.libraryCollapsed;
      void prefsState.libraryWidth;
      void prefsState.collectionsPanelOpen;
      void prefsState.collectionsPanelWidth;
      void prefsState.recents.length;
      // Track tabs structurally: count + each citekey + each preview
      // flag (so promoting a tab from preview to permanent triggers a
      // session re-save).
      const signature = tabsState.tabs.map((t) => `${t.citekey}|${t.preview ? "p" : "P"}`).join("\n");
      void signature;
      scheduleSessionSave();
    });

    // tab-state/{citekey}.json: per-paper PDF state.
    $effect(() => {
      for (const t of tabsState.tabs) {
        void t.pdfPage;
        void t.pdfZoom;
        void t.scrollPos.pdf;
        void t.scrollPos.note;
      }
      // We can't tell which tab changed, so schedule saves for all open tabs.
      // The debounce keeps disk traffic down.
      for (const t of tabsState.tabs) scheduleTabStateSave(t.citekey);
    });
  });
  return stop;
}

// Suppress dead-code warning — pushRecent is invoked elsewhere (tabs.svelte.ts);
// re-exporting here keeps a single entry point for session-related helpers.
export { pushRecent };

// Re-export the Session type so consumers get a single import surface.
export type { Session };

import type { Tab } from "../lib/vault";
import { pushRecent } from "./prefs.svelte";

interface TabsState {
  tabs: Tab[];
  activeIndex: number;
  /** Bumped by ⌘T / ⌘O so Library can focus the search input. */
  searchFocusToken: number;
  /** Bumped by ⌘⇧F so the active tab's PDFView can open its find panel. */
  pdfFindFocusToken: number;
}

function freshTab(citekey: string, preview: boolean): Tab {
  return {
    citekey,
    pdfPage: 1,
    pdfZoom: "auto",
    scrollPos: { pdf: 0, note: 0 },
    preview,
  };
}

export const tabsState = $state<TabsState>({
  tabs: [],
  activeIndex: -1,
  searchFocusToken: 0,
  pdfFindFocusToken: 0,
});

export function activeTab(): Tab | null {
  if (tabsState.activeIndex < 0) return null;
  return tabsState.tabs[tabsState.activeIndex] ?? null;
}

function findPreviewIdx(): number {
  return tabsState.tabs.findIndex((t) => t.preview);
}

/**
 * Single-click semantics — opens the paper in the ephemeral preview
 * slot. Behaviour:
 *
 *   - Paper already open in some tab → just focus it (preview state
 *     of that tab is left as-is).
 *   - A preview tab already exists → replace its content with this
 *     paper, keep it as the preview slot, focus it.
 *   - No preview tab → append a new preview tab.
 *
 * The previous "always-replace-active-tab" semantics is gone: if the
 * user is on a permanent tab and single-clicks something else, the
 * permanent tab stays untouched and the new paper lands in the
 * preview slot (creating one if needed).
 */
export function openInTab(citekey: string): void {
  pushRecent(citekey);
  const existing = tabsState.tabs.findIndex((t) => t.citekey === citekey);
  if (existing >= 0) {
    tabsState.activeIndex = existing;
    return;
  }
  const previewIdx = findPreviewIdx();
  if (previewIdx >= 0) {
    const next = [...tabsState.tabs];
    next[previewIdx] = freshTab(citekey, true);
    tabsState.tabs = next;
    tabsState.activeIndex = previewIdx;
    return;
  }
  tabsState.tabs = [...tabsState.tabs, freshTab(citekey, true)];
  tabsState.activeIndex = tabsState.tabs.length - 1;
}

/**
 * Cmd-click / middle-click / double-click semantics — opens the paper
 * as a permanent tab. If the paper is already open in the preview
 * slot, promote that tab to permanent (don't open a duplicate).
 */
export function openInNewTab(citekey: string): void {
  pushRecent(citekey);
  const existing = tabsState.tabs.findIndex((t) => t.citekey === citekey);
  if (existing >= 0) {
    if (tabsState.tabs[existing].preview) {
      const next = [...tabsState.tabs];
      next[existing] = { ...next[existing], preview: false };
      tabsState.tabs = next;
    }
    tabsState.activeIndex = existing;
    return;
  }
  tabsState.tabs = [...tabsState.tabs, freshTab(citekey, false)];
  tabsState.activeIndex = tabsState.tabs.length - 1;
}

/** Promote a tab from preview to permanent. No-op if already permanent
 *  or index out of range. */
export function promoteToPermanent(idx: number): void {
  if (idx < 0 || idx >= tabsState.tabs.length) return;
  const t = tabsState.tabs[idx];
  if (!t.preview) return;
  const next = [...tabsState.tabs];
  next[idx] = { ...t, preview: false };
  tabsState.tabs = next;
}

export function closeTab(idx: number): void {
  if (idx < 0 || idx >= tabsState.tabs.length) return;
  const next = tabsState.tabs.filter((_, i) => i !== idx);
  let nextIdx = tabsState.activeIndex;
  if (next.length === 0) {
    nextIdx = -1;
  } else if (idx < tabsState.activeIndex) {
    nextIdx = tabsState.activeIndex - 1;
  } else if (idx === tabsState.activeIndex) {
    nextIdx = Math.min(idx, next.length - 1);
  }
  tabsState.tabs = next;
  tabsState.activeIndex = nextIdx;
}

export function closeActiveTab(): void {
  if (tabsState.activeIndex >= 0) closeTab(tabsState.activeIndex);
}

export function closeAllTabs(): void {
  tabsState.tabs = [];
  tabsState.activeIndex = -1;
}

/** Cycle by delta (+1 or -1), wrapping. */
export function cycleTab(delta: number): void {
  if (tabsState.tabs.length === 0) return;
  const n = tabsState.tabs.length;
  tabsState.activeIndex = (tabsState.activeIndex + delta + n) % n;
}

/** ⌘1..⌘9 — 1-indexed; values past the end no-op. */
export function jumpToTab(oneBased: number): void {
  const idx = oneBased - 1;
  if (idx >= 0 && idx < tabsState.tabs.length) tabsState.activeIndex = idx;
}

/** ⌘T / ⌘O — request focus on the library search input. */
export function requestSearchFocus(): void {
  tabsState.searchFocusToken++;
}

/** ⌘⇧F — request focus on the active tab's PDF find panel. */
export function requestPdfFindFocus(): void {
  tabsState.pdfFindFocusToken++;
}

/** Mutate the active tab's PDF page/zoom/scroll. */
export function updateActiveTabPdf(patch: Partial<Pick<Tab, "pdfPage" | "pdfZoom">> & {
  pdfScroll?: number;
}): void {
  const idx = tabsState.activeIndex;
  if (idx < 0) return;
  const cur = tabsState.tabs[idx];
  const next = { ...cur };
  if (patch.pdfPage !== undefined) next.pdfPage = patch.pdfPage;
  if (patch.pdfZoom !== undefined) next.pdfZoom = patch.pdfZoom;
  if (patch.pdfScroll !== undefined) next.scrollPos = { ...cur.scrollPos, pdf: patch.pdfScroll };
  const tabs = [...tabsState.tabs];
  tabs[idx] = next;
  tabsState.tabs = tabs;
}

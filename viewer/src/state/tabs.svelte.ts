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

function freshTab(citekey: string): Tab {
  return {
    citekey,
    pdfPage: 1,
    pdfZoom: "auto",
    scrollPos: { pdf: 0, note: 0 },
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

/** Replace current tab (or open one if none). Focuses an existing tab if already open. */
export function openInTab(citekey: string): void {
  pushRecent(citekey);
  const existing = tabsState.tabs.findIndex((t) => t.citekey === citekey);
  if (existing >= 0) {
    tabsState.activeIndex = existing;
    return;
  }
  if (tabsState.tabs.length === 0 || tabsState.activeIndex < 0) {
    tabsState.tabs = [...tabsState.tabs, freshTab(citekey)];
    tabsState.activeIndex = tabsState.tabs.length - 1;
    return;
  }
  const next = [...tabsState.tabs];
  next[tabsState.activeIndex] = freshTab(citekey);
  tabsState.tabs = next;
}

/** Always open in a new tab (also focuses an existing tab if already open). */
export function openInNewTab(citekey: string): void {
  pushRecent(citekey);
  const existing = tabsState.tabs.findIndex((t) => t.citekey === citekey);
  if (existing >= 0) {
    tabsState.activeIndex = existing;
    return;
  }
  tabsState.tabs = [...tabsState.tabs, freshTab(citekey)];
  tabsState.activeIndex = tabsState.tabs.length - 1;
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

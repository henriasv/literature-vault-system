/**
 * Persistent organizing-view state.
 *
 * The Organizing view (`CollectionsPanel.svelte`) is mounted via an
 * `{#if prefsState.collectionsPanelOpen}` block in App.svelte, so it
 * gets unmounted whenever the user switches back to Reading. To stop
 * that from blowing away the user's multi-select, the open preview,
 * and the papers-vs-inbox subview, those fields live here at module
 * scope. They survive component re-mounts as long as the app process
 * is alive (not persisted across app restarts — that's a separate
 * concern; session.svelte.ts would handle it if we ever want it).
 *
 * Transient UI state (open menus, modal dialogs) stays local to the
 * component — re-opening Organizing should give a clean menu state.
 */

export type SortKey = "title" | "author" | "journal" | "year" | "added";

interface OrganizeState {
  /** Which subview the right pane renders: the paper table or the
   *  unfiled-PDFs Inbox panel. */
  viewMode: "papers" | "inbox";

  /** Multi-select set: citekeys that the user has ticked in the table.
   *  Reactivity is achieved by reassigning the field to a fresh Set
   *  on every mutation (the existing component pattern). */
  selected: Set<string>;

  /** Open preview overlay (paper table row). Mutually exclusive with
   *  previewInboxPath. */
  previewCitekey: string | null;

  /** Open preview overlay (inbox row). Mutually exclusive with
   *  previewCitekey. */
  previewInboxPath: string | null;

  /** Paper table sort column. */
  sortBy: SortKey;

  /** Paper table sort direction. */
  sortDir: "asc" | "desc";

  /** Slugs of collection-tree folders the user has expanded. */
  expanded: Set<string>;

  /** Show papers marked hidden in the paper table. */
  showAllHidden: boolean;

  /** Tag-chip rail expanded vs collapsed. */
  tagsExpanded: boolean;
}

export const organizeState = $state<OrganizeState>({
  viewMode: "papers",
  selected: new Set<string>(),
  previewCitekey: null,
  previewInboxPath: null,
  sortBy: "author",
  sortDir: "asc",
  expanded: new Set<string>(),
  showAllHidden: false,
  tagsExpanded: false,
});

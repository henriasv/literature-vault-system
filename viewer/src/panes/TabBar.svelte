<script lang="ts">
  import { tabsState, closeTab } from "../state/tabs.svelte";
  import { libraryState } from "../state/library.svelte";
  import { paperLabel } from "../lib/vault";
  import { getCurrentWindow } from "@tauri-apps/api/window";

  function tabLabel(citekey: string): string {
    const p = libraryState.papers.find((q) => q.citekey === citekey);
    return p ? paperLabel(p) : citekey;
  }

  /** Empty area of the tab strip (after the rightmost tab) is also a
   *  drag handle for the OS window — matches the macOS Safari / Chrome
   *  pattern. mousedown on the strip's bare surface drags; clicks that
   *  land on a tab or its close button are left alone for the tab's
   *  own onmousedown to handle. */
  function onBarMouseDown(e: MouseEvent): void {
    if (e.button !== 0) return;
    const t = e.target as HTMLElement;
    if (t.closest(".tab, button, a, input, [role=\"button\"], [role=\"tab\"]")) {
      return;
    }
    e.preventDefault();
    getCurrentWindow()
      .startDragging()
      .catch((err) => console.error("startDragging (tab bar) failed:", err));
  }
</script>

<!-- svelte-ignore a11y_interactive_supports_focus -->
<div
  class="tabbar"
  role="tablist"
  data-tauri-drag-region
  onmousedown={onBarMouseDown}>
  {#each tabsState.tabs as tab, i (tab.citekey)}
    <div
      role="tab"
      tabindex={i === tabsState.activeIndex ? 0 : -1}
      aria-selected={i === tabsState.activeIndex}
      class="tab"
      class:active={i === tabsState.activeIndex}
      onmousedown={(e) => {
        if (e.button === 1) {
          e.preventDefault();
          closeTab(i);
        } else if (e.button === 0) {
          tabsState.activeIndex = i;
        }
      }}
    >
      <span class="label">{tabLabel(tab.citekey)}</span>
      <button
        class="close"
        title="Close tab"
        aria-label="Close tab"
        onclick={(e) => {
          e.stopPropagation();
          closeTab(i);
        }}>×</button>
    </div>
  {/each}
</div>

<style>
  /* Tab strip — direction-b.jsx B_PdfViewer top:
     height 38px, padding 0 16px, items align flex-end, no gap,
     border-bottom 1px ink12, background panelAlt.
     Active tab: panel bg (cream), border-top 2px accent, side borders 0.5px,
     marginBottom -1 to lap the strip's bottom border.
     Inactive tab: transparent, ink50, weight 500. */
  .tabbar {
    display: flex;
    align-items: flex-end;
    background: var(--panel-alt);
    overflow-x: auto;
    flex-shrink: 0;
    height: 38px;
    padding: 0 16px;
    border-bottom: 1px solid var(--ink-12);
  }
  .tab {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 14px 9px;
    cursor: pointer;
    font-family: var(--serif);
    font-size: 12px;
    font-weight: 500;
    color: var(--ink-50);
    user-select: none;
    white-space: nowrap;
    background: transparent;
    border-top: 2px solid transparent;
    border-left: 0.5px solid transparent;
    border-right: 0.5px solid transparent;
    margin-bottom: -1px;
    letter-spacing: -0.1px;
  }
  .tab:hover {
    color: var(--ink-70);
  }
  .tab.active {
    color: var(--ink);
    font-weight: 600;
    background: var(--backdrop);
    border-top-color: var(--accent);
    border-left-color: var(--ink-12);
    border-right-color: var(--ink-12);
  }
  .label {
    max-width: 220px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .close {
    width: 14px;
    height: 14px;
    line-height: 1;
    border: 0;
    border-radius: 0;
    padding: 0;
    background: transparent;
    color: var(--ink-30);
    font-size: 11px;
    opacity: 0.6;
  }
  .tab:hover .close,
  .tab.active .close {
    opacity: 1;
  }
  .close:hover {
    color: var(--ink);
  }
</style>

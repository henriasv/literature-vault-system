<script lang="ts">
  /**
   * Global READ / ORGANIZE / REVIEW segmented control.
   *
   * Mounted once in App.svelte at a window-fixed position next to the
   * macOS traffic lights. Single source of truth — no per-pane copy —
   * so the labels can't drift between modes regardless of underlying
   * pane layout (left rail in Read/Review, full-window overlay in
   * Organize).
   *
   * Active state and click handling both read/write `prefsState.viewMode`
   * directly so this component takes no props.
   */
  import { prefsState } from "../state/prefs.svelte";
  import { reviewState } from "../state/review.svelte";

  /* Total review papers across every project. Refreshed by the
   * `review:changed` watcher in App.svelte and by the boot-time call,
   * so the badge stays current regardless of which view is on screen. */
  const reviewCount = $derived(
    reviewState.projects.reduce((sum, p) => sum + p.paperCount, 0),
  );

  function go(mode: "reading" | "organize" | "review") {
    if (prefsState.viewMode !== mode) {
      prefsState.viewMode = mode;
    }
  }
</script>

<div class="view-switch" role="tablist" aria-label="View">
  <button
    class="seg"
    class:on={prefsState.viewMode === "reading"}
    role="tab"
    aria-selected={prefsState.viewMode === "reading"}
    onclick={() => go("reading")}
    title="Reading view (PDF + notes)">Read</button>
  <button
    class="seg"
    class:on={prefsState.viewMode === "organize"}
    role="tab"
    aria-selected={prefsState.viewMode === "organize"}
    onclick={() => go("organize")}
    title="Organizing view (collections + library)">Organize</button>
  <button
    class="seg"
    class:on={prefsState.viewMode === "review"}
    role="tab"
    aria-selected={prefsState.viewMode === "review"}
    onclick={() => go("review")}
    title="Reviewing view (grade student work)">
    <span class="seg-label">Review</span>
    {#if reviewCount > 0}
      <span class="seg-count">{reviewCount}</span>
    {/if}
  </button>
</div>

<style>
  /* Window-fixed. Top + left numbers picked so the strip vertical
     centre lines up with the traffic-light dots (their centre sits
     ~14px from the top of the window on macOS with a 38px strip), and
     so there's a comfortable horizontal gap past the rightmost dot
     (the close/min/zoom group ends around x=78). z-index sits above
     any pane content (organize overlay = 20, reader chrome ~10) but
     below modals (~950). */
  .view-switch {
    position: fixed;
    top: 0;
    left: 0;
    height: 38px;
    padding-left: 100px;
    padding-right: 20px;
    z-index: 50;
    display: inline-flex;
    align-items: center;
    gap: 20px;
    pointer-events: none; /* gap area shouldn't eat the strip's drag */
    -webkit-app-region: drag;
  }
  .seg {
    position: relative;
    pointer-events: auto;
    -webkit-app-region: no-drag;
    padding: 1px 0 3px;
    background: transparent;
    color: var(--ink-30);
    border: 0;
    border-radius: 0;
    font-family: var(--sans);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    cursor: pointer;
    display: inline-flex;
    align-items: baseline;
    gap: 6px;
    line-height: 1;
  }
  .seg:hover:not(.on) {
    color: var(--ink-70);
  }
  .seg.on {
    color: var(--ink);
    cursor: default;
    box-shadow: inset 0 -1.5px 0 0 var(--accent);
  }
  .seg-count {
    font-family: var(--sans);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0;
    color: var(--accent);
  }
</style>

<script lang="ts">
  /**
   * Anchored READ / ORGANIZE / REVIEW segmented control.
   *
   * Lives at the very top-left of every view (above the library pane in
   * reading, above the collections tree in organizing, above the project
   * tree in reviewing). The DOM is positioned identically in all three —
   * same height (28px), same padding, same gap from the traffic-light
   * placeholder — so the cursor lands on the same (x, y) regardless of
   * which view is active.
   *
   * Visual: plain labels with a 1.5px accent underline on the active one
   * (instead of a filled pill). REVIEW carries a small accent-coloured
   * paper-count badge, sourced from reviewState — useful as an at-a-
   * glance "n papers awaiting attention" in the chrome.
   */
  import { prefsState, type ViewMode } from "../state/prefs.svelte";
  import { reviewState } from "../state/review.svelte";

  let { active }: { active: ViewMode } = $props();

  /* Total review papers across every project. Refreshed via the
   * `review:changed` watcher in App.svelte, so the badge stays current
   * even when the rail is on another view. */
  const reviewCount = $derived(
    reviewState.projects.reduce((sum, p) => sum + p.paperCount, 0),
  );

  function go(mode: ViewMode) {
    if (prefsState.viewMode !== mode) {
      prefsState.viewMode = mode;
    }
  }
</script>

<div class="view-switch" role="tablist" aria-label="View">
  <button
    class="seg"
    class:on={active === "reading"}
    role="tab"
    aria-selected={active === "reading"}
    onclick={() => go("reading")}
    title="Reading view (PDF + notes)">Read</button>
  <button
    class="seg"
    class:on={active === "organize"}
    role="tab"
    aria-selected={active === "organize"}
    onclick={() => go("organize")}
    title="Organizing view (collections + library)">Organize</button>
  <button
    class="seg"
    class:on={active === "review"}
    role="tab"
    aria-selected={active === "review"}
    onclick={() => go("review")}
    title="Reviewing view (grade student work)">
    <span class="seg-label">Review</span>
    {#if reviewCount > 0}
      <span class="seg-count">{reviewCount}</span>
    {/if}
  </button>
</div>

<style>
  /* Plain text labels, generous gap between them, accent underline on
     the active one. No outer border or filled pill — the strip blends
     into the surrounding masthead chrome. */
  .view-switch {
    display: inline-flex;
    align-items: center;
    height: 28px;
    background: transparent;
    flex-shrink: 0;
    gap: 20px;
  }
  .seg {
    position: relative;
    padding: 4px 0;
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
  }
  .seg:hover:not(.on) {
    color: var(--ink-70);
  }
  /* Active gets full-ink colour + a 1.5px accent underline that sits
     directly under the baseline of the caps (border-bottom on the
     button itself so it hugs the text width — no separate element). */
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

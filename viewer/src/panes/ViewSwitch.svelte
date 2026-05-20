<script lang="ts">
  /**
   * Anchored Reading / Organizing / Reviewing segmented control.
   *
   * Lives at the very top-left of every view (above the library pane in
   * reading, above the collections tree in organizing, above the project
   * tree in reviewing). The DOM is positioned identically in all three —
   * same height (28px), same padding, same gap from the traffic-light
   * placeholder — so the cursor lands on the same (x, y) regardless of
   * which view is active.
   */
  import { prefsState, type ViewMode } from "../state/prefs.svelte";

  let { active }: { active: ViewMode } = $props();

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
    title="Reading view (PDF + notes)">Reading</button>
  <button
    class="seg"
    class:on={active === "organize"}
    role="tab"
    aria-selected={active === "organize"}
    onclick={() => go("organize")}
    title="Organizing view (collections + library)">Organizing</button>
  <button
    class="seg"
    class:on={active === "review"}
    role="tab"
    aria-selected={active === "review"}
    onclick={() => go("review")}
    title="Reviewing view (grade student work)">Reviewing</button>
</div>

<style>
  .view-switch {
    display: inline-flex;
    align-items: stretch;
    height: 28px;
    border: 1px solid var(--ink);
    background: var(--panel);
    flex-shrink: 0;
  }
  .seg {
    padding: 0 12px;
    background: transparent;
    color: var(--ink-70);
    border: 0;
    border-radius: 0;
    font-family: var(--sans);
    font-size: 9.5px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    cursor: pointer;
    min-width: 82px;
  }
  .seg.on {
    background: var(--ink);
    color: var(--backdrop);
    cursor: default;
  }
  .seg:hover:not(.on) {
    color: var(--ink);
  }
</style>

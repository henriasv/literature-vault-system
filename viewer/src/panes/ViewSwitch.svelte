<script lang="ts">
  /**
   * Anchored Reading / Organizing segmented control.
   *
   * Lives at the very top-left of both the reading view (above the library
   * pane) and the organize view (above the collections tree). The DOM is
   * positioned identically in both — same height (28px), same padding, same
   * gap from the traffic-light placeholder — so the cursor lands on the same
   * (x, y) regardless of which view is active. Clicking the inactive segment
   * toggles `prefsState.collectionsPanelOpen`.
   */
  import { prefsState } from "../state/prefs.svelte";

  type Mode = "reading" | "organize";
  let { active }: { active: Mode } = $props();

  function flip() {
    prefsState.collectionsPanelOpen = !prefsState.collectionsPanelOpen;
  }
</script>

<div class="view-switch" role="tablist" aria-label="View">
  <button
    class="seg"
    class:on={active === "reading"}
    role="tab"
    aria-selected={active === "reading"}
    onclick={() => active === "organize" && flip()}
    title="Reading view (PDF + notes)">Reading</button>
  <button
    class="seg"
    class:on={active === "organize"}
    role="tab"
    aria-selected={active === "organize"}
    onclick={() => active === "reading" && flip()}
    title="Organizing view (collections + library)">Organizing</button>
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
    padding: 0 14px;
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
    min-width: 92px;
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

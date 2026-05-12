<!--
  Global right-click context menu. Mounted once at the App root. Reads
  ctxMenuState — when open, renders a small floating menu at the click
  coordinates with the items the caller provided.

  Click outside / Esc / scroll closes. We do clamping to the viewport so the
  menu doesn't overflow off the right or bottom edge.
-->
<script lang="ts">
  import { ctxMenuState, closeCtxMenu } from "../state/ctxmenu.svelte";
  import type { MenuItem } from "../state/ctxmenu.svelte";

  /* Clamp the menu position so it stays on-screen even when right-click
   * happens near the bottom-right of the window. We need the rendered size
   * to compute the clamp, so we read it after mount via a bind:this ref. */
  let root: HTMLDivElement | undefined = $state();
  let style = $derived.by(() => {
    if (!ctxMenuState.open) return "";
    const w = root?.offsetWidth ?? 220;
    const h = root?.offsetHeight ?? 0;
    const x = Math.min(ctxMenuState.x, window.innerWidth - w - 8);
    const y = Math.min(ctxMenuState.y, window.innerHeight - h - 8);
    return `left: ${Math.max(8, x)}px; top: ${Math.max(8, y)}px;`;
  });

  function onItemClick(item: MenuItem) {
    if (item.disabled) return;
    closeCtxMenu();
    /* Defer the action so the menu can unmount before the handler fires —
     * stops a handler that opens another modal from racing with the close. */
    queueMicrotask(() => item.onclick());
  }

  function onWindowKey(e: KeyboardEvent) {
    if (e.key === "Escape" && ctxMenuState.open) {
      e.preventDefault();
      closeCtxMenu();
    }
  }
  function onWindowMousedown(e: MouseEvent) {
    if (!ctxMenuState.open) return;
    if (root && root.contains(e.target as Node)) return;
    closeCtxMenu();
  }
  function onWindowScroll() {
    if (ctxMenuState.open) closeCtxMenu();
  }
</script>

<svelte:window
  onkeydown={onWindowKey}
  onmousedown={onWindowMousedown}
  onscroll={onWindowScroll}
/>

{#if ctxMenuState.open}
  <div
    bind:this={root}
    class="ctxmenu"
    role="menu"
    style={style}
  >
    {#each ctxMenuState.items as item, i (i)}
      <button
        type="button"
        class="ctxmenu-item"
        class:primary={item.kind === "primary"}
        class:danger={item.kind === "danger"}
        disabled={item.disabled}
        onclick={() => onItemClick(item)}
        role="menuitem"
      >
        {item.label}
      </button>
    {/each}
  </div>
{/if}

<style>
  .ctxmenu {
    position: fixed;
    z-index: 9998;
    min-width: 200px;
    background: var(--panel, #fff);
    border: 1px solid var(--ink-12, rgba(26, 22, 18, 0.18));
    border-radius: 5px;
    padding: 4px;
    box-shadow:
      0 2px 0 rgba(0, 0, 0, 0.02),
      0 16px 36px -12px rgba(26, 22, 18, 0.28);
    display: flex;
    flex-direction: column;
  }
  .ctxmenu-item {
    appearance: none;
    background: transparent;
    border: 0;
    text-align: left;
    padding: 6px 12px;
    border-radius: 3px;
    font: inherit;
    font-size: 13px;
    color: var(--ink, #1a1612);
    cursor: pointer;
  }
  .ctxmenu-item:hover:not(:disabled) {
    background: var(--panel-alt, #f6f1e6);
  }
  .ctxmenu-item.primary {
    color: var(--accent, #7a3a14);
    font-weight: 500;
  }
  .ctxmenu-item.danger {
    color: var(--accent-bright, #b03020);
  }
  .ctxmenu-item:disabled {
    opacity: 0.45;
    cursor: default;
  }
</style>

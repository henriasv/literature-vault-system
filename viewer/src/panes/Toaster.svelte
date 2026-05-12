<script lang="ts">
  import { toastState } from "../state/toast.svelte";
</script>

<div class="toaster">
  {#each toastState.items as t (t.id)}
    <div class="toast" class:err={t.kind === "error"}>{t.message}</div>
  {/each}
</div>

<style>
  .toaster {
    position: fixed;
    bottom: 16px;
    right: 16px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    z-index: 1000;
    pointer-events: none;
  }
  .toast {
    background: rgba(20, 20, 20, 0.92);
    color: white;
    padding: 8px 12px;
    border-radius: 4px;
    font-size: 12px;
    max-width: 360px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
  }
  .toast.err {
    background: rgba(170, 30, 30, 0.95);
  }
</style>

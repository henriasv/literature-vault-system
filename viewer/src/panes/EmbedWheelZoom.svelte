<script lang="ts">
  /**
   * Trackpad pinch-to-zoom + ⌘-wheel zoom for the EmbedPDF viewport.
   *
   * macOS / WKWebView synthesises a wheel event with `ctrlKey: true`
   * for trackpad pinch gestures (even when no real ctrl is held).
   * That's the only signal we get from the OS; we also accept
   * metaKey-modified wheels so ⌘+scroll behaves the same.
   *
   * Lives inside the EmbedPDF plugin tree (so `useZoom` resolves),
   * wraps the Viewport in a transparent host that captures the wheel
   * before the Scroller does, and calls `requestZoomBy` with the
   * cursor as the focus point so the page zooms toward the pinch
   * centre instead of the top-left corner.
   *
   * The listener is attached with `passive: false` via addEventListener
   * — Svelte 5's `onwheel` may be coerced to passive by the browser,
   * which would silently swallow `preventDefault()` and let the page
   * scroll during a pinch.
   */
  import type { Snippet } from "svelte";
  import { onMount } from "svelte";
  import { useZoom } from "@embedpdf/plugin-zoom/svelte";

  let {
    documentId,
    children,
  }: { documentId: string; children?: Snippet } = $props();

  const zoom = useZoom(() => documentId);
  let host: HTMLDivElement;

  function onWheel(e: WheelEvent) {
    // Plain scroll → let it bubble to the Scroller for normal scrolling.
    // Modified wheel (trackpad pinch sets ctrlKey, ⌘+scroll sets metaKey)
    // → zoom toward the cursor.
    if (!e.ctrlKey && !e.metaKey) return;
    const provides = zoom.provides;
    if (!provides) return;
    e.preventDefault();
    e.stopPropagation();

    /* deltaY signs:
     *   - pinch-out (fingers apart)  → negative deltaY → zoom in
     *   - pinch-in  (fingers together) → positive deltaY → zoom out
     * Negate so positive delta = zoom in, matching the user's gesture.
     * The 0.01 scale factor produces ~1% zoom per typical wheel tick;
     * trackpads emit many small deltas, mice fewer large ones, so a
     * single multiplier gives reasonable behaviour for both. */
    const delta = -e.deltaY * 0.01;

    /* Zoom plugin's Point is viewport-relative ({vx, vy}), not page
     * coordinates. Convert clientX/Y by subtracting the host's
     * bounding rect — the host wraps the Viewport one-to-one, so its
     * top-left is the viewport origin. */
    const rect = host.getBoundingClientRect();
    provides.requestZoomBy(delta, {
      vx: e.clientX - rect.left,
      vy: e.clientY - rect.top,
    });
  }

  onMount(() => {
    host.addEventListener("wheel", onWheel, { passive: false });
    return () => host.removeEventListener("wheel", onWheel);
  });
</script>

<div bind:this={host} class="wheel-zoom-host">
  {@render children?.()}
</div>

<style>
  .wheel-zoom-host {
    /* Pass-through container — the Viewport / Scroller inside fills
       100% of available space (flex child of .doc-area), so we just
       need to occupy the same slot. */
    display: flex;
    flex: 1;
    min-height: 0;
    min-width: 0;
    flex-direction: column;
  }
</style>

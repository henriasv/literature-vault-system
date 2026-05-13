<!--
  Custom renderer for PDF TEXT (sticky-note) annotations.

  Why we override EmbedPDF's built-in TextRenderer:
    1. The bundled built-in stores its click handler at
       `div.__pointerdown = …` (the older Svelte delegation convention).
       Svelte 5.55's runtime delegates via a Symbol-keyed store and never
       finds it — the icon shows a `cursor: pointer` on hover but clicks
       do nothing.
    2. The built-in only fires onClick (= select). Dragging only works
       *after* the sticky is selected because AnnotationContainer's drag
       surface is `pointer-events: none` until then. So moving an
       unselected sticky takes two gestures: click to select, click-and-
       drag to move.

  This renderer fixes both: we bind `onpointerdown` as a normal attribute
  (not delegated) AND we implement press-and-drag directly via the
  plugin's `moveAnnotation(..., "delta")` API. A 5px threshold separates
  click (→ select via onClick) from drag (→ apply deltas, no select).
-->
<script lang="ts">
  import { useAnnotationCapability } from "@embedpdf/plugin-annotation/svelte";
  import { useScroll } from "@embedpdf/plugin-scroll/svelte";
  import type { PdfAnnotationObject } from "@embedpdf/models";
  import { maybeReparentByY } from "../lib/annotation-reparent";

  type AnnObj = {
    id: string;
    pageIndex: number;
    strokeColor?: string;
    color?: string;
    opacity?: number;
    custom?: { bookmark?: boolean; comment?: string };
  };

  type Props = {
    annotation: { object: AnnObj };
    currentObject: AnnObj;
    isSelected: boolean;
    isEditing: boolean;
    scale: number;
    pageIndex: number;
    documentId: string;
    onClick?: (e: PointerEvent | MouseEvent) => void;
    appearanceActive?: boolean;
  };
  let {
    annotation,
    currentObject,
    isSelected,
    scale,
    documentId,
    onClick,
    appearanceActive = false,
  }: Props = $props();

  const ann = useAnnotationCapability();
  const scroll = useScroll(() => documentId);

  /* A bookmark annotation = TEXT subtype with custom.bookmark = true.
   * Rendered as a ribbon icon in the accent colour to distinguish it
   * from yellow sticky notes. Only one bookmark per paper, set/moved
   * from the toolbar. */
  const isBookmark = $derived(currentObject.custom?.bookmark === true);
  const color = $derived(currentObject.strokeColor ?? currentObject.color ?? "#FFCD45");
  const opacity = $derived(currentObject.opacity ?? 1);

  /* "Loose" drag: keep pointer-events auto even when selected so the
   * framework's clamped drag-surface never fires — our
   * `moveAnnotation('delta')` handler doesn't clamp, so the user can
   * fling the sticky onto the recess or onto a neighbouring page. We
   * reparent on drag end (see onPointerUp). */
  const pointerEvents = $derived(onClick ? "auto" : "none");
  const cursor = $derived(onClick ? "move" : "default");

  /* Contrast-derived stroke colour for the line glyphs inside the icon. */
  const lineColor = $derived.by(() => {
    const hex = (color || "").replace("#", "");
    if (hex.length !== 6) return "#1a1612";
    const r = parseInt(hex.slice(0, 2), 16);
    const g = parseInt(hex.slice(2, 4), 16);
    const b = parseInt(hex.slice(4, 6), 16);
    const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    return lum > 0.6 ? "#1a1612" : "#fcfaf5";
  });

  /* ---- Click vs drag --------------------------------------------------
   * On pointerdown we capture the pointer; pointermove past THRESHOLD
   * starts drag mode and applies the cursor delta as a page-coordinate
   * delta to the annotation's rect (via moveAnnotation 'delta'). On
   * pointerup, if no drag happened we treat it as a click and call
   * onClick (which selects + opens the comment menu).
   */
  const DRAG_THRESHOLD_PX = 5;
  let drag: {
    pointerId: number;
    startX: number;
    startY: number;
    lastX: number;
    lastY: number;
    moved: boolean;
  } | null = null;

  function onPointerDown(e: PointerEvent) {
    /* Only the primary button — right-click/middle-click should not
     * initiate a drag or selection. */
    if (e.button !== 0) return;
    /* Block the browser's default mouse-down → start-text-selection
     * behaviour, otherwise sweeping the pointer across PDF text glyphs
     * during a drag flashes a selection on the page underneath. */
    e.preventDefault();
    e.stopPropagation();
    drag = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      lastX: e.clientX,
      lastY: e.clientY,
      moved: false,
    };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  }

  function onPointerMove(e: PointerEvent) {
    if (!drag || e.pointerId !== drag.pointerId) return;
    e.preventDefault();
    e.stopPropagation();
    const dx = e.clientX - drag.startX;
    const dy = e.clientY - drag.startY;
    if (!drag.moved && Math.hypot(dx, dy) > DRAG_THRESHOLD_PX) {
      drag.moved = true;
    }
    if (drag.moved) {
      const stepX = (e.clientX - drag.lastX) / scale;
      const stepY = (e.clientY - drag.lastY) / scale;
      drag.lastX = e.clientX;
      drag.lastY = e.clientY;
      ann.provides?.moveAnnotation(
        annotation.object.pageIndex,
        annotation.object.id,
        { x: stepX, y: stepY },
        "delta",
      );
    }
  }

  function onPointerUp(e: PointerEvent) {
    if (!drag || e.pointerId !== drag.pointerId) return;
    e.preventDefault();
    e.stopPropagation();
    const wasMoved = drag.moved;
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      /* releasePointerCapture throws if not the active capture target —
       * harmless. */
    }
    drag = null;
    if (!wasMoved) {
      onClick?.(e);
      return;
    }
    /* Bookmark is a singleton anchored to its containing page — moving
     * it across pages is the toolbar's "move bookmark here" button's
     * job, not a side-effect of a manual drag. Skip reparenting. */
    if (isBookmark) return;
    maybeReparentByY({
      annotation: annotation.object as unknown as PdfAnnotationObject,
      scroll: scroll.provides,
      ann: ann.provides,
    });
  }
</script>

<div
  style:position="absolute"
  style:inset="0"
  style:z-index="2"
  style:pointer-events={pointerEvents}
  style:cursor={cursor}
  style:touch-action="none"
  style:user-select="none"
  onpointerdown={onPointerDown}
  onpointermove={onPointerMove}
  onpointerup={onPointerUp}
  onpointercancel={onPointerUp}
  role="button"
  tabindex={onClick ? 0 : -1}
  aria-label={isBookmark ? "Bookmark" : "Sticky note"}
>
  {#if !appearanceActive}
    {#if isBookmark}
      <!-- Ribbon-style bookmark icon: a rectangle with a notch cut out
           of the bottom. Same 20×20 viewBox as the sticky shape so the
           icon visually matches its rect. -->
      <svg
        viewBox="0 0 20 20"
        width="100%"
        height="100%"
        style="position: absolute; inset: 0; pointer-events: none;"
      >
        <path
          d="M 4 1 L 16 1 L 16 18 L 10 14 L 4 18 Z"
          stroke-width="1"
          stroke-linejoin="miter"
          fill={color}
          {opacity}
          stroke="#1a1612"
        />
      </svg>
    {:else}
      <svg
        viewBox="0 0 20 20"
        width="100%"
        height="100%"
        style="position: absolute; inset: 0; pointer-events: none;"
      >
        <path
          d="M 0.5 15.5 L 0.5 0.5 L 19.5 0.5 L 19.5 15.5 L 8.5 15.5 L 6.5 19.5 L 4.5 15.5 Z"
          stroke-width="1"
          stroke-linejoin="miter"
          fill={color}
          {opacity}
          stroke={lineColor}
        />
        <line x1="2.5" y1="4.25" x2="17.5" y2="4.25" stroke-width="1" stroke={lineColor} />
        <line x1="2.5" y1="8" x2="17.5" y2="8" stroke-width="1" stroke={lineColor} />
        <line x1="2.5" y1="11.75" x2="17.5" y2="11.75" stroke-width="1" stroke={lineColor} />
      </svg>
    {/if}
  {/if}
</div>

<!--
  Custom renderer for PDF shape annotations: SQUARE, CIRCLE, LINE, INK.

  Why we override the bundled renderers:
    EmbedPDF's bundled SquareRenderer / CircleRenderer / LineRenderer /
    InkRenderer all attach their click handler via the old Svelte
    delegation convention (`elem.__pointerdown = …`). Under Svelte
    5.55's runtime, delegation goes through a Symbol-keyed store, so
    those handlers are never invoked. Visually the shapes render, but
    clicking them does nothing — you can't select, drag, or open the
    comment menu.

  This single renderer covers all four shape types. We pick the SVG
  geometry off `currentObject.type` and bind `onpointerdown` as a
  normal attribute, plus implement press-and-drag via
  `moveAnnotation('delta')` the same way the sticky-note renderer does
  (5px click-vs-drag threshold).
-->
<script lang="ts">
  import { useAnnotationCapability } from "@embedpdf/plugin-annotation/svelte";
  import { useScroll } from "@embedpdf/plugin-scroll/svelte";
  import { PdfAnnotationSubtype, type PdfAnnotationObject } from "@embedpdf/models";
  import { maybeReparentByY } from "../lib/annotation-reparent";

  type Point = { x: number; y: number };
  type Rect = { origin: Point; size: { width: number; height: number } };

  type ShapeObj = {
    id: string;
    pageIndex: number;
    type: number;
    strokeColor?: string;
    color?: string;
    opacity?: number;
    strokeWidth?: number;
    rect?: Rect;
    /* LINE-specific */
    linePoints?: { start: Point; end: Point };
    /* INK-specific */
    inkList?: { points: Point[] }[];
    custom?: { comment?: string };
  };

  type Props = {
    annotation: { object: ShapeObj };
    currentObject: ShapeObj;
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

  const strokeColor = $derived(
    currentObject.strokeColor ?? currentObject.color ?? "#7a3a14",
  );
  const opacity = $derived(currentObject.opacity ?? 1);
  const strokeWidth = $derived(currentObject.strokeWidth ?? 1.5);

  /* viewBox uses page-coordinate units local to the annotation's rect,
   * so we can plot geometry (linePoints, inkList points) in page coords
   * directly after subtracting rect.origin. The container div is sized
   * in scaled pixels by AnnotationContainer, so SVG width="100%" + the
   * page-coord viewBox handles the scale-to-pixels conversion. */
  const rect = $derived(currentObject.rect);
  const vbW = $derived(rect?.size.width ?? 0);
  const vbH = $derived(rect?.size.height ?? 0);

  /* Convert a page-coord point to local viewBox coords (relative to the
   * annotation's top-left). */
  function toLocal(p: Point): Point {
    if (!rect) return { x: 0, y: 0 };
    return { x: p.x - rect.origin.x, y: p.y - rect.origin.y };
  }

  /* INK: build an SVG path string from the inkList polylines. Each
   * polyline becomes a "Mx,y Lx,y Lx,y …" subpath; we concatenate
   * them so a single <path> renders the whole annotation. */
  const inkPath = $derived.by(() => {
    const strokes = currentObject.inkList;
    if (!strokes || strokes.length === 0) return "";
    const parts: string[] = [];
    for (const stroke of strokes) {
      const pts = stroke.points;
      if (!pts || pts.length === 0) continue;
      const first = toLocal(pts[0]);
      parts.push(`M${first.x.toFixed(2)},${first.y.toFixed(2)}`);
      for (let i = 1; i < pts.length; i++) {
        const p = toLocal(pts[i]);
        parts.push(`L${p.x.toFixed(2)},${p.y.toFixed(2)}`);
      }
    }
    return parts.join(" ");
  });

  const lineStart = $derived.by(() =>
    currentObject.linePoints ? toLocal(currentObject.linePoints.start) : null,
  );
  const lineEnd = $derived.by(() =>
    currentObject.linePoints ? toLocal(currentObject.linePoints.end) : null,
  );

  /* "Loose" drag: keep pointer-events auto even when selected so the
   * framework's clamped-to-page drag surface never fires — our own
   * `moveAnnotation('delta')` handler doesn't clamp, so the user can
   * fling the shape onto the recess or onto a neighbouring page, and
   * we reparent on drag end (see onPointerUp). Resize handles live
   * outside the renderer's body so they keep working. */
  const pointerEvents = $derived(onClick ? "auto" : "none");
  const cursor = $derived(onClick ? "move" : "default");

  /* ---- Click vs drag --------------------------------------------------
   * Same pattern as EmbedStickyNoteRenderer: capture pointer, threshold
   * separates a tap (→ onClick → select + open menu) from a drag (→
   * moveAnnotation 'delta' per pointermove step). */
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
    if (e.button !== 0) return;
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
      /* releasePointerCapture throws if not the active capture target. */
    }
    drag = null;
    if (!wasMoved) {
      onClick?.(e);
      return;
    }
    /* If the user flung the shape off the current page vertically,
     * re-anchor it to the neighbouring page. One step per drag —
     * spanning more than one page over requires another drag. */
    maybeReparentByY({
      annotation: annotation.object as unknown as PdfAnnotationObject,
      scroll: scroll.provides,
      ann: ann.provides,
    });
  }

  const ariaLabel = $derived.by(() => {
    switch (currentObject.type) {
      case PdfAnnotationSubtype.SQUARE: return "Rectangle annotation";
      case PdfAnnotationSubtype.CIRCLE: return "Ellipse annotation";
      case PdfAnnotationSubtype.LINE:   return "Line annotation";
      case PdfAnnotationSubtype.INK:    return "Ink annotation";
      default: return "Shape annotation";
    }
  });
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
  aria-label={ariaLabel}
>
  {#if !appearanceActive && rect && vbW > 0 && vbH > 0}
    <svg
      viewBox="0 0 {vbW} {vbH}"
      width="100%"
      height="100%"
      style="position: absolute; inset: 0; pointer-events: none; overflow: visible;"
      preserveAspectRatio="none"
    >
      {#if currentObject.type === PdfAnnotationSubtype.SQUARE}
        <rect
          x={strokeWidth / 2}
          y={strokeWidth / 2}
          width={Math.max(0, vbW - strokeWidth)}
          height={Math.max(0, vbH - strokeWidth)}
          fill="none"
          stroke={strokeColor}
          stroke-width={strokeWidth}
          {opacity}
        />
      {:else if currentObject.type === PdfAnnotationSubtype.CIRCLE}
        <ellipse
          cx={vbW / 2}
          cy={vbH / 2}
          rx={Math.max(0, vbW / 2 - strokeWidth / 2)}
          ry={Math.max(0, vbH / 2 - strokeWidth / 2)}
          fill="none"
          stroke={strokeColor}
          stroke-width={strokeWidth}
          {opacity}
        />
      {:else if currentObject.type === PdfAnnotationSubtype.LINE && lineStart && lineEnd}
        <line
          x1={lineStart.x}
          y1={lineStart.y}
          x2={lineEnd.x}
          y2={lineEnd.y}
          stroke={strokeColor}
          stroke-width={strokeWidth}
          stroke-linecap="round"
          {opacity}
        />
      {:else if currentObject.type === PdfAnnotationSubtype.INK && inkPath}
        <path
          d={inkPath}
          fill="none"
          stroke={strokeColor}
          stroke-width={strokeWidth}
          stroke-linecap="round"
          stroke-linejoin="round"
          {opacity}
        />
      {/if}
    </svg>
  {/if}
</div>

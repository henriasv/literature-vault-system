<!--
  Custom renderer for PDF FREETEXT annotations (our "post-it" / always-
  open text box). Replaces EmbedPDF's bundled FreeText renderer for the
  same reasons we override the TEXT renderer:

    1. The bundled renderer stores its click handler via the older
       Svelte delegation convention (`div.__pointerdown = …`) which
       Svelte 5.55's runtime doesn't dispatch — clicks never reach
       onClick, so an unselected post-it can't be selected and
       therefore can't be dragged.

    2. The note doesn't grow with its content. We want it to behave
       like a yellow post-it that expands as the user types so text
       never gets clipped by the `overflow: hidden` on the editor.

  This renderer:
    - Paints the post-it background, dark ink, soft border.
    - Drives selection via a normal `onpointerdown` attribute.
    - Implements click-vs-drag (press-and-drag past 5 px → move via
      `moveAnnotation('delta')`; short press → onClick).
    - When the framework flips `isEditing` on, focuses an inline
      contenteditable span. As the user types, the rect grows: we
      measure scrollHeight (and width for long unwrapped words) and
      patch the annotation's rect so the box always shows the full
      text. The final commit happens on blur (the framework's
      `isEditing` toggle to false).
-->
<script lang="ts">
  import { useAnnotationCapability } from "@embedpdf/plugin-annotation/svelte";
  import { useScroll } from "@embedpdf/plugin-scroll/svelte";
  import type { PdfAnnotationObject } from "@embedpdf/models";
  import { maybeReparentByY } from "../lib/annotation-reparent";

  type AnnObj = {
    id: string;
    pageIndex: number;
    rect: { origin: { x: number; y: number }; size: { width: number; height: number } };
    contents?: string;
    fontSize?: number;
    fontFamily?: string;
    fontColor?: string;
    color?: string;
    backgroundColor?: string;
    opacity?: number;
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
    isEditing,
    scale,
    documentId,
    onClick,
    appearanceActive = false,
  }: Props = $props();

  const ann = useAnnotationCapability();
  const scroll = useScroll(() => documentId);

  /* Visual: post-it yellow fill, dark ink, subtle border. Defaults
   * win when the annotation hasn't been patched with explicit values. */
  const bg = $derived(
    currentObject.color ?? currentObject.backgroundColor ?? "#FFF59D",
  );
  const fg = $derived(currentObject.fontColor ?? "#1A1612");
  const fontSize = $derived(currentObject.fontSize ?? 14);
  const opacity = $derived(currentObject.opacity ?? 1);

  const outerW = $derived(currentObject.rect.size.width * scale);
  const outerH = $derived(currentObject.rect.size.height * scale);

  /* "Loose" drag: keep pointer-events auto in every state except when
   * onClick is unset. Our drag bypasses the framework's clamped drag
   * surface so the user can fling the post-it off the page; we
   * reparent on drag end. While editing, the contenteditable inside
   * the post-it captures pointer events itself. */
  const pointerEvents = $derived(onClick ? "auto" : "none");
  const cursor = $derived(
    isEditing ? "text" : isSelected ? "move" : onClick ? "move" : "default",
  );

  /* ---- Editor focus + auto-grow ----------------------------------------
   * On isEditing turning true, focus the contenteditable span and select
   * its contents (or place caret at end, depending on whether the
   * placeholder is still there). On every input, recompute the rect to
   * fit the text. */
  let editorRef = $state<HTMLSpanElement | undefined>(undefined);
  $effect(() => {
    const el = editorRef;
    if (!isEditing || !el) return;
    queueMicrotask(() => {
      el.focus();
      const sel = window.getSelection?.();
      if (!sel) return;
      const range = document.createRange();
      range.selectNodeContents(el);
      const isPlaceholder =
        (currentObject.contents ?? "").trim() === "" ||
        (currentObject.contents ?? "") === "Insert text";
      if (!isPlaceholder) range.collapse(false);
      sel.removeAllRanges();
      sel.addRange(range);
    });
  });

  function fitToContent() {
    const el = editorRef;
    if (!el) return;
    /* scrollHeight is the natural rendered height of the content
     * (clipped portion + visible portion) at the current scale, in
     * CSS px. Convert back to PDF page coords by dividing by scale.
     * We grow width only when content overflows horizontally (long
     * unwrappable words / a much wider line); otherwise we keep the
     * current width so the note stays a stable column. Minimum width
     * is the current width so it never shrinks mid-edit. */
    const minPadCss = 6; // matches CSS padding below (top + bottom = 12 ≈ scale-agnostic small)
    const naturalHeightCss = el.scrollHeight + minPadCss * 2;
    const naturalWidthCss = el.scrollWidth + minPadCss * 2;
    const curW = currentObject.rect.size.width;
    const curH = currentObject.rect.size.height;
    const newW = Math.max(curW, naturalWidthCss / scale);
    const newH = Math.max(curH, naturalHeightCss / scale);
    if (Math.abs(newW - curW) < 0.5 && Math.abs(newH - curH) < 0.5) return;
    ann.provides?.updateAnnotation(annotation.object.pageIndex, annotation.object.id, {
      rect: {
        origin: { ...currentObject.rect.origin },
        size: { width: newW, height: newH },
      },
    } as Parameters<NonNullable<typeof ann.provides>["updateAnnotation"]>[2]);
  }

  function onInput() {
    fitToContent();
  }

  function onBlur() {
    const el = editorRef;
    if (!el) return;
    /* Commit final contents AND a final fit, in case the framework's
     * own blur handler hasn't run yet. updateAnnotation merges, so
     * setting both fields together is fine. */
    const text = el.innerText.replace(/ /g, " ");
    ann.provides?.updateAnnotation(annotation.object.pageIndex, annotation.object.id, {
      contents: text,
    } as Parameters<NonNullable<typeof ann.provides>["updateAnnotation"]>[2]);
    fitToContent();
  }

  /* ---- Click vs drag (only when NOT editing) ---------------------------
   * Mirrors EmbedStickyNoteRenderer: capture pointer, threshold for
   * drag, apply page-coord delta via moveAnnotation, fall back to
   * onClick for a tap. Drag is suppressed while in edit mode because
   * the editor needs the pointer events for text-cursor placement. */
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
    if (isEditing) return; // let the contenteditable handle it
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
      /* harmless if not the active capture target */
    }
    drag = null;
    if (!wasMoved) {
      onClick?.(e);
      return;
    }
    maybeReparentByY({
      annotation: annotation.object as unknown as PdfAnnotationObject,
      scroll: scroll.provides,
      ann: ann.provides,
    });
  }
</script>

<div
  class="ft-host"
  style:position="absolute"
  style:left="0"
  style:top="0"
  style:width="{outerW}px"
  style:height="{outerH}px"
  style:z-index="2"
  style:pointer-events={pointerEvents}
  style:cursor={cursor}
  style:opacity={appearanceActive ? 0 : 1}
  style:touch-action="none"
  onpointerdown={onPointerDown}
  onpointermove={onPointerMove}
  onpointerup={onPointerUp}
  onpointercancel={onPointerUp}
  role={onClick ? "button" : undefined}
  tabindex={onClick ? 0 : -1}
  aria-label="Text box"
>
  <span
    class="ft-editor"
    bind:this={editorRef}
    contenteditable={isEditing}
    role={isEditing ? "textbox" : undefined}
    aria-multiline="true"
    style:background={bg}
    style:color={fg}
    style:font-size="{fontSize * scale}px"
    style:opacity={opacity}
    oninput={onInput}
    onblur={onBlur}
  >{currentObject.contents ?? ""}</span>
</div>

<style>
  .ft-host {
    user-select: none;
  }
  .ft-editor {
    display: block;
    width: 100%;
    height: 100%;
    box-sizing: border-box;
    padding: 6px 8px;
    border-radius: 2px;
    line-height: 1.25;
    font-family: var(--serif, "Source Serif 4", Georgia, serif);
    overflow: hidden;
    /* No outline / no text-cursor styling while not editing; the host
       div drives the cursor in that mode. */
    outline: none;
    cursor: inherit;
    white-space: pre-wrap;
    word-wrap: break-word;
    box-shadow: 0 1px 0 rgba(26, 22, 18, 0.10), 0 4px 12px -6px rgba(26, 22, 18, 0.15);
  }
  .ft-editor:focus {
    cursor: text;
    user-select: text;
  }
</style>

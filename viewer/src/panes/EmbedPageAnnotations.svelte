<!--
  Thin wrapper that mounts `<AnnotationLayer>` for a single page with the
  right scale read live from the zoom plugin.

  AnnotationLayer is the composite component that includes:
    - <Annotations>          renders existing annotations from state
    - <TextMarkup>           text-markup tool interactions (highlight, …)
    - <AnnotationPaintLayer> hosts each tool's pointer handler so clicks
                             with the active tool create annotations
  Without the third we get rendering but no per-tool click-to-create —
  i.e. the sticky-note (`textComment`) tool would be silent.

  We pass `annotationRenderers={[stickyRenderer]}` to override the built-
  in TEXT renderer. Why: the bundled built-in stores its onClick at
  `div.__pointerdown = …`, the old Svelte delegation convention, but
  Svelte 5.55 delegates via a Symbol-keyed store and never finds it —
  the sticky shows a pointer cursor but clicks do nothing. Our renderer
  uses the non-delegated `onpointerdown={onClick}` attribute form.
-->
<script lang="ts">
  import {
    AnnotationLayer,
    createRenderer,
    useAnnotationCapability,
  } from "@embedpdf/plugin-annotation/svelte";
  import { useZoom } from "@embedpdf/plugin-zoom/svelte";
  import {
    PdfAnnotationSubtype,
    type PdfAnnotationObject,
    type PdfTextAnnoObject,
    type PdfFreeTextAnnoObject,
    type PdfSquareAnnoObject,
    type PdfCircleAnnoObject,
    type PdfLineAnnoObject,
    type PdfInkAnnoObject,
  } from "@embedpdf/models";
  import EmbedAnnotationSelectionMenu from "./EmbedAnnotationSelectionMenu.svelte";
  import EmbedStickyNoteRenderer from "./EmbedStickyNoteRenderer.svelte";
  import EmbedFreeTextRenderer from "./EmbedFreeTextRenderer.svelte";
  import EmbedShapeRenderer from "./EmbedShapeRenderer.svelte";
  import EmbedLinkRenderer from "./EmbedLinkRenderer.svelte";
  import { pdfNavState } from "../state/pdfNav.svelte";

  type Props = {
    documentId: string;
    pageIndex: number;
  };
  let { documentId, pageIndex }: Props = $props();

  const zoom = useZoom(() => documentId);
  const scale = $derived(zoom.state.currentZoomLevel ?? 1);

  const stickyRenderer = createRenderer({
    id: "text", // same id replaces built-in via merge-by-id
    matches: (a: PdfAnnotationObject): a is PdfTextAnnoObject =>
      a.type === PdfAnnotationSubtype.TEXT && !a.inReplyToId,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    component: EmbedStickyNoteRenderer as any,
    interactionDefaults: { isDraggable: true, isResizable: false, isRotatable: false },
  });

  /* Custom FreeText renderer: replaces EmbedPDF's built-in to (a) bind
   * onpointerdown as a normal attribute so single-click selection works,
   * (b) implement press-and-drag, and (c) auto-grow the rect as the user
   * types so text isn't clipped. See EmbedFreeTextRenderer.svelte. */
  const freeTextRenderer = createRenderer({
    id: "freeText",
    matches: (a: PdfAnnotationObject): a is PdfFreeTextAnnoObject =>
      a.type === PdfAnnotationSubtype.FREETEXT && a.intent !== "FreeTextCallout",
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    component: EmbedFreeTextRenderer as any,
    interactionDefaults: { isDraggable: true, isResizable: true, isRotatable: false },
    onDoubleClick: (id, setEditingId) => setEditingId(id),
  });

  /* Shape renderers: SQUARE / CIRCLE / LINE / INK all share one custom
   * component for the same reason as TEXT — the bundled Svelte
   * renderers use `__pointerdown =` delegation that Svelte 5.55 doesn't
   * pick up, so the shapes render but ignore clicks. The component
   * picks geometry off the annotation type. */
  const squareRenderer = createRenderer({
    id: "square",
    matches: (a: PdfAnnotationObject): a is PdfSquareAnnoObject =>
      a.type === PdfAnnotationSubtype.SQUARE,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    component: EmbedShapeRenderer as any,
    interactionDefaults: { isDraggable: true, isResizable: true, isRotatable: false },
  });
  const circleRenderer = createRenderer({
    id: "circle",
    matches: (a: PdfAnnotationObject): a is PdfCircleAnnoObject =>
      a.type === PdfAnnotationSubtype.CIRCLE,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    component: EmbedShapeRenderer as any,
    interactionDefaults: { isDraggable: true, isResizable: true, isRotatable: false },
  });
  const lineRenderer = createRenderer({
    id: "line",
    matches: (a: PdfAnnotationObject): a is PdfLineAnnoObject =>
      a.type === PdfAnnotationSubtype.LINE,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    component: EmbedShapeRenderer as any,
    interactionDefaults: { isDraggable: true, isResizable: true, isRotatable: false },
  });
  const inkRenderer = createRenderer({
    id: "ink",
    matches: (a: PdfAnnotationObject): a is PdfInkAnnoObject =>
      a.type === PdfAnnotationSubtype.INK,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    component: EmbedShapeRenderer as any,
    interactionDefaults: { isDraggable: true, isResizable: false, isRotatable: false },
  });
  /* LINK renderer: opens URI links in the OS default browser (via
   * `open_path_external`) and delegates internal page jumps to the
   * annotation plugin. Replaces the bundled renderer whose click was
   * wired via the broken `__click` delegation. */
  const linkRenderer = createRenderer({
    id: "link",
    matches: (a: PdfAnnotationObject) =>
      a.type === PdfAnnotationSubtype.LINK,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    component: EmbedLinkRenderer as any,
    interactionDefaults: { isDraggable: false, isResizable: false, isRotatable: false },
  });

  /* Flash overlay: when the Annotations tab in the right pane single-
   * clicks a row, pdfNavState.flash is set for ~800ms. If the annotation
   * lives on THIS page, draw a thin accent-coloured outline around its
   * bounding rect that fades out via CSS animation. Keying the div on
   * the flash timestamp restarts the animation when the same row is
   * clicked twice in a row. */
  const annotation = useAnnotationCapability();
  type FlashRect = { x: number; y: number; w: number; h: number };
  const flashRect = $derived.by<FlashRect | null>(() => {
    const flash = pdfNavState.flash;
    if (!flash) return null;
    const ann = annotation.provides?.getAnnotationById(flash.annotationId);
    if (!ann) return null;
    if (ann.object.pageIndex !== pageIndex) return null;
    const r = ann.object.rect;
    if (!r) return null;
    return {
      x: r.origin.x * scale,
      y: r.origin.y * scale,
      w: r.size.width * scale,
      h: r.size.height * scale,
    };
  });
  const flashKey = $derived(pdfNavState.flash?.ts ?? 0);
</script>

<AnnotationLayer
  {documentId}
  {pageIndex}
  {scale}
  annotationRenderers={[
    stickyRenderer,
    freeTextRenderer,
    squareRenderer,
    circleRenderer,
    lineRenderer,
    inkRenderer,
    linkRenderer,
  ]}
>
  {#snippet selectionMenuSnippet(props)}
    <EmbedAnnotationSelectionMenu {documentId} {...props} />
  {/snippet}
</AnnotationLayer>

{#if flashRect}
  {#key flashKey}
    <div
      class="flash-outline"
      style:left="{flashRect.x}px"
      style:top="{flashRect.y}px"
      style:width="{flashRect.w}px"
      style:height="{flashRect.h}px"
    ></div>
  {/key}
{/if}

<style>
  .flash-outline {
    position: absolute;
    pointer-events: none;
    box-sizing: border-box;
    border: 1.5px solid var(--accent, #7a3a14);
    border-radius: 2px;
    box-shadow: 0 0 0 3px rgba(122, 58, 20, 0.18);
    z-index: 20;
    animation: flash-fade 0.8s ease-out forwards;
  }
  @keyframes flash-fade {
    0%, 55% { opacity: 1; }
    100% { opacity: 0; }
  }
</style>

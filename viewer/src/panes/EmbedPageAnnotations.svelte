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
  } from "@embedpdf/plugin-annotation/svelte";
  import { useZoom } from "@embedpdf/plugin-zoom/svelte";
  import { PdfAnnotationSubtype, type PdfAnnotationObject, type PdfTextAnnoObject } from "@embedpdf/models";
  import EmbedAnnotationSelectionMenu from "./EmbedAnnotationSelectionMenu.svelte";
  import EmbedStickyNoteRenderer from "./EmbedStickyNoteRenderer.svelte";

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
</script>

<AnnotationLayer
  {documentId}
  {pageIndex}
  {scale}
  annotationRenderers={[stickyRenderer]}
>
  {#snippet selectionMenuSnippet(props)}
    <EmbedAnnotationSelectionMenu {documentId} {...props} />
  {/snippet}
</AnnotationLayer>

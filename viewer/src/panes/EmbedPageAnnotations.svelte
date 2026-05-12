<!--
  Thin wrapper that mounts `<Annotations>` for a single page with the right
  scale + rotation read live from the zoom plugin.

  The Scroller's `renderPage` snippet only hands out `PageLayout`
  (pageNumber, pageIndex, x, y, width, height, rotatedWidth, …) — *not*
  the current `scale` / `rotation`. `<Annotations>` requires both, and
  passing `scale={1}` leaves overlays offset from the underlying text at
  any zoom other than 100%. `useZoom` only works from inside the EmbedPDF
  plugin tree, hence this child component rather than a top-level read.
-->
<script lang="ts">
  import { Annotations } from "@embedpdf/plugin-annotation/svelte";
  import { useZoom } from "@embedpdf/plugin-zoom/svelte";
  import EmbedAnnotationSelectionMenu from "./EmbedAnnotationSelectionMenu.svelte";

  type Props = {
    documentId: string;
    pageIndex: number;
    pageWidth: number;
    pageHeight: number;
  };
  let { documentId, pageIndex, pageWidth, pageHeight }: Props = $props();

  const zoom = useZoom(() => documentId);
  const scale = $derived(zoom.state.currentZoomLevel ?? 1);
</script>

<Annotations
  {documentId}
  {pageIndex}
  {scale}
  rotation={0}
  {pageWidth}
  {pageHeight}
>
  {#snippet selectionMenuSnippet(props)}
    <EmbedAnnotationSelectionMenu {documentId} {...props} />
  {/snippet}
</Annotations>

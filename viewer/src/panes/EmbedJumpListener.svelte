<!--
  In-tree consumer for `pdfNavState.pendingJump` requests.

  Lives inside <EmbedPDF> so it can call `useScroll` / `useAnnotationCapability`.
  Other panes write the request; we translate it into:
    1. `scroll.scrollToPage({...})` — with `pageCoordinates` + `alignX/Y = 50`
       to put the highlight midpoint at viewport centre when supplied.
    2. `annotation.selectAnnotation(pageIndex, id)` if `openAnnotationId` set
       — deferred so the target page has time to virtualize into the DOM
       and its <Annotations> selectionMenuSnippet can mount before the
       selection-state change is observed.
  Filters by citekey so only the visible paper's request runs.
-->
<script lang="ts">
  import { useScroll } from "@embedpdf/plugin-scroll/svelte";
  import { useAnnotationCapability } from "@embedpdf/plugin-annotation/svelte";
  import { pdfNavState, consumeJump } from "../state/pdfNav.svelte";

  type Props = { documentId: string; citekey: string };
  let { documentId, citekey }: Props = $props();

  const scroll = useScroll(() => documentId);
  const annotation = useAnnotationCapability();

  /* A `dblclick` is preceded by two `click` events; the first one already
   * scrolled the target page into the DOM, so by the time we get here the
   * page is virtualized and <Annotations> is mounted. The tiny delay
   * remains as a safety margin in case the page was on the edge of the
   * virtual window. */
  const SELECT_AFTER_SCROLL_MS = 60;
  let selectTimer: ReturnType<typeof setTimeout> | null = null;

  $effect(() => {
    const req = pdfNavState.pendingJump;
    if (!req) return;
    if (req.citekey !== citekey) return;
    const sp = scroll.provides;
    if (!sp) return;

    sp.scrollToPage({
      pageNumber: req.pageNumber,
      pageCoordinates: req.centerOn,
      alignX: req.centerOn ? 50 : undefined,
      alignY: req.centerOn ? 50 : undefined,
      behavior: "smooth",
    });

    if (req.openAnnotationId) {
      const id = req.openAnnotationId;
      const pageIdx = req.pageNumber - 1;
      if (selectTimer !== null) clearTimeout(selectTimer);
      selectTimer = setTimeout(() => {
        selectTimer = null;
        annotation.provides?.selectAnnotation(pageIdx, id);
      }, SELECT_AFTER_SCROLL_MS);
    }

    consumeJump();
  });
</script>

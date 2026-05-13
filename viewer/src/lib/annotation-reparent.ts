/* Loose-drag reparenting helper.
 *
 * Our custom annotation renderers (sticky-note, shape, free-text) handle
 * drag via `moveAnnotation('delta')`, which the EmbedPDF plugin does NOT
 * clamp to the page's bounds — the user can fling an annotation into the
 * cream "recess" area or all the way onto a neighbouring page.
 *
 * After the drag ends we check whether the annotation's vertical centre
 * has crossed off the current page; if so, transfer it to the
 * neighbouring page (one step per drag, multi-page jumps would need
 * chained drags). We don't reparent horizontally — the canvas is
 * vertically scrolling so horizontal overruns just dangle into the side
 * recess and that's fine.
 *
 * Mechanism: the annotation plugin's `updateAnnotation` reducer patches
 * fields but keeps the annotation indexed under its original page —
 * cross-page moves require delete-then-create (same trick the bookmark
 * "move here" already uses). To preserve the comment / colour / etc.,
 * we shallow-clone the annotation object and only mutate `pageIndex`
 * and `rect.origin.y`.
 */

import type { PdfAnnotationObject } from "@embedpdf/models";

const VIEWPORT_GAP = 10; // matches ViewportPluginPackage config

type ScrollProvides = {
  getSpreadPagesWithRotatedSize?: () => Array<Array<{ rotatedSize: { width: number; height: number } }>>;
};

type AnnotationProvides = {
  deleteAnnotation: (pageIndex: number, id: string) => unknown;
  createAnnotation: (pageIndex: number, ann: PdfAnnotationObject) => unknown;
  deselectAnnotation?: () => unknown;
};

/** Returns true if a reparent happened. */
export function maybeReparentByY(args: {
  annotation: PdfAnnotationObject;
  scroll: ScrollProvides | undefined | null;
  ann: AnnotationProvides | undefined | null;
}): boolean {
  const { annotation, scroll, ann } = args;
  if (!scroll || !ann) return false;
  const rect = annotation.rect;
  if (!rect) return false;

  const spreads = scroll.getSpreadPagesWithRotatedSize?.();
  if (!spreads || spreads.length === 0) return false;
  /* Flatten spreads → ordered page list. In vertical scroll strategy
   * each spread holds a single page, so the flat list's index === the
   * annotation's pageIndex. */
  const flat: { height: number }[] = [];
  for (const spread of spreads) {
    for (const p of spread) {
      flat.push({ height: p.rotatedSize.height });
    }
  }

  const pageIndex = annotation.pageIndex;
  const currentPage = flat[pageIndex];
  if (!currentPage) return false;

  const centerY = rect.origin.y + rect.size.height / 2;

  let targetIndex = pageIndex;
  let newOriginY = rect.origin.y;

  if (centerY < 0 && pageIndex > 0) {
    targetIndex = pageIndex - 1;
    /* origin.y on the previous page = prevPage.height + gap + current
     * origin.y (which is negative). Lands the annotation at the same
     * visual y in the previous page's coordinate system. */
    newOriginY = flat[targetIndex].height + VIEWPORT_GAP + rect.origin.y;
  } else if (centerY > currentPage.height && pageIndex < flat.length - 1) {
    targetIndex = pageIndex + 1;
    newOriginY = rect.origin.y - currentPage.height - VIEWPORT_GAP;
  } else {
    return false;
  }

  /* Build the replacement annotation. We use a fresh id (and Date)
   * rather than reusing the originals — the bundled bookmark "move"
   * does the same, and reusing the original id while the plugin still
   * holds a reference to it (e.g., selection state) leaves things in
   * a broken half-deleted state where the annotation freezes and
   * disappears from the sidecar list. */
  const newAnnotation = {
    ...annotation,
    id: typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${annotation.id}-${Date.now()}`,
    pageIndex: targetIndex,
    rect: {
      ...rect,
      origin: { x: rect.origin.x, y: newOriginY },
    },
    modified: new Date(),
  } as PdfAnnotationObject;

  /* Deselect before delete so the framework's selection state doesn't
   * keep a dangling reference to the about-to-be-removed annotation —
   * that was the source of the "all annotations freeze" symptom. Then
   * delete + create. The reducer indexes annotations by page in
   * state.pages, so an in-place pageIndex update would leave a phantom
   * on the original page; delete-then-create with a fresh id is the
   * cleanest cross-page move. */
  ann.deselectAnnotation?.();
  ann.deleteAnnotation(pageIndex, annotation.id);
  ann.createAnnotation(targetIndex, newAnnotation);
  return true;
}

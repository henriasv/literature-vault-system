/* Cross-pane PDF navigation + sidecar invalidation signals.
 *
 * The PDF lives inside the EmbedPDF plugin tree (only components rendered
 * as children of <EmbedPDF> can call its hooks), so other panes can't
 * directly call scrollToPage. They write a `pendingJump` request here; a
 * tiny listener inside the tree (EmbedJumpListener.svelte) consumes it.
 *
 * Two distinct UX gestures plug in here:
 *   - `requestJump(...)`  — scroll-and-centre, optionally followed by a
 *     `selectAnnotation()` so the comment menu pops up. Used for "open"
 *     (double-click in the Annotations list).
 *   - `requestFlash(...)` — draws a transient thin outline around an
 *     annotation for ~1.4s so the user sees *which one* was clicked
 *     without the modal-style comment editor opening. Used for "navigate"
 *     (single-click in the Annotations list).
 *
 * `sidecarVersion` is bumped by EmbedPDFView whenever it writes a fresh
 * annotation sidecar so the Annotations tab re-fetches reactively.
 */

interface JumpRequest {
  citekey: string;
  pageNumber: number; // 1-based, matches scrollToPage's API
  centerOn?: { x: number; y: number }; // PDF page coordinates
  /** When set, selectAnnotation() runs after the scroll (with a small delay
   *  so the target page has time to virtualize into the DOM and mount its
   *  <Annotations> selectionMenuSnippet). */
  openAnnotationId?: string;
  ts: number;
}

interface FlashRequest {
  citekey: string;
  annotationId: string;
  /** Distinct timestamp so clicking the same row twice re-triggers the flash. */
  ts: number;
}

/** "Move the bookmark to wherever the user is currently reading." Triggered
 *  from the right-pane bookmark bar (NoteEditor) and consumed by the
 *  EmbedPdfToolbar mounted for that citekey, which knows the current
 *  viewport position. */
interface BookmarkMoveRequest {
  citekey: string;
  ts: number;
}

interface DocMeta {
  totalPages: number;
}

interface PdfNavState {
  pendingJump: JumpRequest | null;
  flash: FlashRequest | null;
  sidecarVersion: number;
  pendingBookmarkMove: BookmarkMoveRequest | null;
  /** Per-citekey doc metadata published by the toolbar once a PDF is open.
   *  The right pane reads this so the bookmark bar can show "p.4/7" even
   *  when it isn't the component that loaded the PDF. Stale-but-harmless
   *  if a PDF is later swapped out — re-populated on next open. */
  documentMeta: Record<string, DocMeta>;
}

export const pdfNavState = $state<PdfNavState>({
  pendingJump: null,
  flash: null,
  sidecarVersion: 0,
  pendingBookmarkMove: null,
  documentMeta: {},
});

export interface JumpOptions {
  centerOn?: { x: number; y: number };
  openAnnotationId?: string;
}

export function requestJump(
  citekey: string,
  pageNumber: number,
  opts?: JumpOptions,
): void {
  pdfNavState.pendingJump = {
    citekey,
    pageNumber,
    centerOn: opts?.centerOn,
    openAnnotationId: opts?.openAnnotationId,
    ts: Date.now(),
  };
}

export function consumeJump(): void {
  pdfNavState.pendingJump = null;
}

const FLASH_MS = 800;
let flashTimer: ReturnType<typeof setTimeout> | null = null;

export function requestFlash(citekey: string, annotationId: string): void {
  if (flashTimer !== null) clearTimeout(flashTimer);
  pdfNavState.flash = { citekey, annotationId, ts: Date.now() };
  flashTimer = setTimeout(() => {
    pdfNavState.flash = null;
    flashTimer = null;
  }, FLASH_MS);
}

export function bumpSidecarVersion(): void {
  pdfNavState.sidecarVersion++;
}

export function requestBookmarkMove(citekey: string): void {
  pdfNavState.pendingBookmarkMove = { citekey, ts: Date.now() };
}

export function consumeBookmarkMove(): void {
  pdfNavState.pendingBookmarkMove = null;
}

export function setDocumentTotalPages(citekey: string, totalPages: number): void {
  /* Mutate-in-place rather than replacing the record so callers that
   * touched the proxy for other citekeys don't see spurious invalidation. */
  const existing = pdfNavState.documentMeta[citekey];
  if (existing && existing.totalPages === totalPages) return;
  pdfNavState.documentMeta = { ...pdfNavState.documentMeta, [citekey]: { totalPages } };
}

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

interface PdfNavState {
  pendingJump: JumpRequest | null;
  flash: FlashRequest | null;
  sidecarVersion: number;
}

export const pdfNavState = $state<PdfNavState>({
  pendingJump: null,
  flash: null,
  sidecarVersion: 0,
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

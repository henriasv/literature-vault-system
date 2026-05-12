/**
 * Internal-drag state shared across views.
 *
 * Why this exists: in the Tauri WKWebView host, the OS-level
 * drag-and-drop handler intercepts every drag in the window — including
 * pure HTML5 drags between DOM elements. The HTML5 `ondragover` and
 * `ondrop` handlers on our tree nodes never fire because WKWebView
 * routes the gesture through the OS layer first. The only place we can
 * observe an in-flight drag is `webview.onDragDropEvent` in App.svelte.
 *
 * The workaround: drag sources (library rows, organize table rows)
 * tell us they've started an internal drag (`startInternalDrag`),
 * App.svelte's OS handler maps each `enter` / `over` / `drop` position
 * to a DOM element via `document.elementFromPoint`, walks up to a node
 * tagged `data-drop-target-slug=…`, and either highlights it
 * (`setHoverSlug`) or executes the drop (`addPaperToCollection`).
 *
 * Drop targets opt in by setting `data-drop-target-slug={slug}` on the
 * element that should accept the drop. The tree's hover styling reads
 * `dndState.hoverSlug` to highlight the currently-targeted node.
 */

import { addPaperToCollection } from "./collections.svelte";
import { toast } from "./toast.svelte";

interface DndState {
  /** True while an internal drag is in flight (between dragstart and
   *  dragend / drop). */
  active: boolean;
  /** Citekeys carried by the drag. Multi-row drags pass the entire
   *  selection; single-row drags pass just that one. */
  citekeys: string[];
  /** Slug of the drop target currently under the cursor. Tree rows
   *  read this to render the drop-target highlight. */
  hoverSlug: string | null;
}

export const dndState = $state<DndState>({
  active: false,
  citekeys: [],
  hoverSlug: null,
});

export function startInternalDrag(citekeys: string[]): void {
  dndState.active = true;
  dndState.citekeys = [...citekeys];
  dndState.hoverSlug = null;
}

export function endInternalDrag(): void {
  dndState.active = false;
  dndState.citekeys = [];
  dndState.hoverSlug = null;
}

export function setHoverSlug(slug: string | null): void {
  if (dndState.hoverSlug !== slug) dndState.hoverSlug = slug;
}

/**
 * Perform the actual collection-add for the current drag, then clear
 * the drag state. Called from HTML5 dragend on the source — Tauri's
 * onDragDropEvent doesn't reliably fire a "drop" event for purely
 * internal drags (the OS only sees the cursor moving, never crossing
 * the window boundary), but the HTML5 dragend on the dragged element
 * fires reliably when the gesture ends.
 *
 * We try `dndState.hoverSlug` first (set by Tauri's over events
 * tracking the cursor) and fall back to elementFromPoint at the
 * dragend event's clientX/Y, in case Tauri's over events didn't fire.
 */
export async function finishInternalDrag(e?: DragEvent): Promise<void> {
  /* Resolve the drop target with a two-step fallback.
   *
   * 1) Prefer the dragend event's clientX/clientY (the actual cursor
   *    position at release) through document.elementFromPoint. This
   *    is the most accurate signal when WKWebView delivers real
   *    coordinates.
   *
   * 2) Fall back to dndState.hoverSlug. Under Tauri/WKWebView the
   *    HTML5 dragend event sometimes arrives with clientX=clientY=0
   *    (the OS handled the gesture and the browser only saw a
   *    synthesised dragend), so step 1 yields nothing. Tauri's "over"
   *    events keep hoverSlug current and pass null whenever the
   *    cursor isn't on a real drop target, so a non-null hoverSlug
   *    at release accurately means the cursor was on that slug when
   *    the user let go. */
  let slug: string | null = null;
  if (e && (e.clientX > 0 || e.clientY > 0)) {
    const el = document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null;
    if (el) {
      const target = el.closest<HTMLElement>("[data-drop-target-slug]");
      if (target) slug = target.getAttribute("data-drop-target-slug");
    }
  }
  if (!slug && dndState.hoverSlug) {
    slug = dndState.hoverSlug;
  }
  const cks = [...dndState.citekeys];
  endInternalDrag();
  if (!slug || cks.length === 0) return;
  let ok = 0;
  let fail = 0;
  for (const ck of cks) {
    try {
      await addPaperToCollection(slug, ck);
      ok++;
    } catch (err) {
      fail++;
      console.error("addPaperToCollection failed", ck, slug, err);
    }
  }
  if (fail === 0) toast(`Added ${ok} → ${slug}`);
  else toast(`Added ${ok}, failed ${fail}`, "error");
}

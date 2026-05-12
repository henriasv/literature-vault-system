<!--
  Small popover that appears next to a text selection, with the four
  highlight colors. Clicking a swatch creates a HIGHLIGHT annotation
  spanning the selection's rects and clears the selection.

  This is the canonical EmbedPDF pattern (matches their
  `SelectionSelectionMenu` example): the SelectionLayer's
  `selectionMenuSnippet` slot mounts us with the selection's bounds +
  page index, and we drive the annotation plugin programmatically. Our
  toolbar's annotation bar still works as a "pre-select a color" flow
  for keyboard-first usage; this menu is the click-driven path.
-->
<script lang="ts">
  import { useAnnotationCapability } from "@embedpdf/plugin-annotation/svelte";
  import { useSelectionCapability } from "@embedpdf/plugin-selection/svelte";
  import { PdfAnnotationSubtype, PdfBlendMode } from "@embedpdf/models";
  import type { MenuWrapperProps } from "@embedpdf/utils/svelte";
  import type { Rect } from "@embedpdf/models";
  import { HIGHLIGHT_COLORS, type HighlightColor } from "../lib/highlight-colors";
  import { appendHighlight } from "../lib/vault";
  import { toast } from "../state/toast.svelte";

  type Props = {
    documentId: string;
    citekey: string;
    rect: Rect;
    menuWrapperProps: MenuWrapperProps;
    selected: boolean;
    context: { type: "selection"; pageIndex: number };
  };
  let { documentId, citekey, rect, menuWrapperProps, selected, context }: Props = $props();

  const annotation = useAnnotationCapability();
  const selection = useSelectionCapability();

  async function createHighlight(color: HighlightColor) {
    const annProv = annotation.provides;
    const selProv = selection.provides?.forDocument(documentId);
    if (!annProv || !selProv) return;

    const pageIndex = context.pageIndex;
    const segmentRects = selProv.getHighlightRectsForPage(pageIndex);
    const bounding = selProv.getBoundingRectForPage(pageIndex);
    if (segmentRects.length === 0 || !bounding) return;

    // Capture the selected text BEFORE creating the annotation —
    // getSelectedText is a Task<string[]>, one string per page the
    // selection spans. We then stash it as the annotation's `contents`
    // (round-trips into the sidecar + an eventual XFDF export) and
    // append it to the note's `## Highlights` section as a record the
    // user can search / cite from.
    let excerpt = "";
    try {
      const parts = await selProv.getSelectedText().toPromise();
      excerpt = (parts ?? []).join(" ").replace(/\s+/g, " ").trim();
    } catch (e) {
      console.warn("[HighlightMenu] failed to read selected text", e);
    }

    annProv.createAnnotation(pageIndex, {
      id: crypto.randomUUID(),
      pageIndex,
      type: PdfAnnotationSubtype.HIGHLIGHT,
      rect: bounding,
      segmentRects,
      strokeColor: color,
      color, // deprecated but some downstream code still reads it
      opacity: 0.5,
      blendMode: PdfBlendMode.Multiply,
      author: "Literature Vault",
      created: new Date(),
      contents: excerpt || undefined,
    });

    selProv.clear();

    if (excerpt) {
      // Fire-and-forget: don't block the UI on the note write. Append
      // is idempotent-ish (same excerpt twice will produce two lines —
      // which is what the user would want for actual duplicates). On
      // failure we surface a toast rather than swallow silently so the
      // user knows the markdown didn't update; the in-PDF highlight
      // still persists via the sidecar regardless.
      void appendHighlight(citekey, pageIndex + 1, excerpt).catch((e) => {
        console.warn("[HighlightMenu] appendHighlight failed", e);
        toast(`Highlight saved, but failed to append to note: ${e}`, "error");
      });
    }
  }
</script>

<span style={menuWrapperProps.style} use:menuWrapperProps.action>
  {#if selected}
    <div
      class="hl-menu"
      style:position="absolute"
      style:top="{rect.size.height + 8}px"
      style:left="50%"
      style:transform="translateX(-50%)"
      style:z-index="1000"
      style:cursor="default"
    >
      {#each HIGHLIGHT_COLORS as c (c)}
        <button
          type="button"
          class="swatch"
          style:--swatch={c}
          onclick={() => createHighlight(c)}
          title="Highlight with {c}"
          aria-label="Highlight with {c}"
        ></button>
      {/each}
    </div>
  {/if}
</span>

<style>
  .hl-menu {
    pointer-events: auto;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 5px 8px;
    border-radius: 6px;
    background: var(--panel, #fff);
    border: 1px solid var(--ink-12, rgba(26, 22, 18, 0.18));
    box-shadow:
      0 2px 0 rgba(0, 0, 0, 0.02),
      0 8px 20px -8px rgba(26, 22, 18, 0.28);
  }
  .swatch {
    appearance: none;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    border: 1px solid var(--ink-12, rgba(26, 22, 18, 0.18));
    background: var(--swatch, #FFEB3B);
    cursor: pointer;
    padding: 0;
    margin: 0;
    transition: transform 0.12s ease, border-color 0.12s ease;
  }
  .swatch:hover {
    transform: scale(1.15);
    border-color: var(--ink, #1a1612);
  }
  .swatch:focus-visible {
    outline: 2px solid var(--accent, #7a3a14);
    outline-offset: 2px;
  }
</style>

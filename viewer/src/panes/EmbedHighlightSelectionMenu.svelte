<!--
  Small popover that appears next to a text selection, with the four
  highlight colors. Clicking a swatch creates a HIGHLIGHT annotation
  spanning the selection's rects and clears the selection.

  This is the canonical EmbedPDF pattern (matches their
  `SelectionSelectionMenu` example): the SelectionLayer's
  `selectionMenuSnippet` slot mounts us with the selection's bounds +
  page index, and we drive the annotation plugin programmatically.

  We capture the selected text into the annotation's `contents` field so
  it round-trips through the JSON sidecar at `Annotations/<citekey>.json`
  — the librarian agent + the export-PDF pipeline read excerpts from
  there. The user's freeform comment on a highlight is a separate field
  (`custom.comment`), edited via EmbedAnnotationSelectionMenu.
-->
<script lang="ts">
  import { useAnnotationCapability } from "@embedpdf/plugin-annotation/svelte";
  import { useSelectionCapability } from "@embedpdf/plugin-selection/svelte";
  import { PdfAnnotationSubtype, PdfBlendMode } from "@embedpdf/models";
  import type { MenuWrapperProps } from "@embedpdf/utils/svelte";
  import type { Rect } from "@embedpdf/models";
  import { HIGHLIGHT_COLORS, type HighlightColor } from "../lib/highlight-colors";

  type Props = {
    documentId: string;
    rect: Rect;
    menuWrapperProps: MenuWrapperProps;
    selected: boolean;
    context: { type: "selection"; pageIndex: number };
  };
  let { documentId, rect, menuWrapperProps, selected, context }: Props = $props();

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

    // Capture the selected text and stash it as the annotation's
    // `contents`. Round-trips through `Annotations/{citekey}.json` for
    // the librarian agent + the eventual PDF export. The user's
    // freeform comment is a separate field on the annotation
    // (`custom.comment`), edited from the click-on-highlight menu.
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

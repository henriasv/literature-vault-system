<!--
  Popover that appears when an existing annotation is selected. Mirrors
  the text-selection menu's shape (same MenuWrapperProps contract) so
  EmbedPDF can position it.

  Two annotation kinds funnel through this menu:

    HIGHLIGHT: `contents` carries the highlighted excerpt (captured at
      creation time), shown read-only at the top of the popover. The
      user's freeform comment lives in `custom.comment` — a non-standard
      payload the PDF spec leaves under `custom` and EmbedPDF preserves
      end-to-end through import/export, so the comment lives in the
      sidecar JSON, not the .md note.

    TEXT (sticky note): `contents` IS the note body (PDF spec). No
      excerpt is shown; the textarea is bound to `contents` directly.

  Enter saves and closes the menu (commit + deselect); Shift+Enter
  inserts a newline; Esc reverts. Save-on-blur is a safety net. Delete
  is styled as the secondary/destructive escape hatch.
-->
<script lang="ts">
  import { useAnnotationCapability } from "@embedpdf/plugin-annotation/svelte";
  import type { MenuWrapperProps } from "@embedpdf/utils/svelte";
  import type { Rect } from "@embedpdf/models";
  import { PdfAnnotationSubtype } from "@embedpdf/models";
  import type { AnnotationSelectionContext } from "@embedpdf/plugin-annotation/svelte";

  type Props = {
    documentId: string;
    rect: Rect;
    menuWrapperProps: MenuWrapperProps;
    selected: boolean;
    context: AnnotationSelectionContext;
  };
  let { rect, menuWrapperProps, selected, context }: Props = $props();

  const annotation = useAnnotationCapability();

  const annType = $derived(context.annotation.object.type);
  const isSticky = $derived(annType === PdfAnnotationSubtype.TEXT);
  const isHighlight = $derived(annType === PdfAnnotationSubtype.HIGHLIGHT);
  /* Shapes that carry their freeform comment under custom.comment (just
   * like highlights). FreeText is excluded because its body lives in
   * `contents` and is edited inline on the page rather than here. */
  const isShape = $derived(
    annType === PdfAnnotationSubtype.SQUARE ||
      annType === PdfAnnotationSubtype.CIRCLE ||
      annType === PdfAnnotationSubtype.LINE ||
      annType === PdfAnnotationSubtype.INK,
  );
  /* Bookmarks are TEXT annotations flagged via `custom.bookmark`. They
   * don't carry user comments — the menu shows a single "Remove
   * bookmark" action instead of the comment textarea. */
  const isBookmark = $derived(
    isSticky &&
      (context.annotation.object.custom as { bookmark?: boolean } | undefined)?.bookmark === true,
  );
  /* Only highlights carry an excerpt (the captured selection text).
   * Sticky notes use `contents` as the note body, shapes don't use it
   * at all — neither should leak a stray excerpt block. */
  const excerpt = $derived<string>(
    isHighlight ? context.annotation.object.contents ?? "" : "",
  );
  const shapeKindLabel = $derived.by(() => {
    switch (annType) {
      case PdfAnnotationSubtype.SQUARE: return "rectangle";
      case PdfAnnotationSubtype.CIRCLE: return "ellipse";
      case PdfAnnotationSubtype.LINE:   return "line";
      case PdfAnnotationSubtype.INK:    return "drawing";
      default: return "annotation";
    }
  });
  const deleteLabel = $derived(
    isSticky ? "Delete note" :
    isHighlight ? "Delete highlight" :
    `Delete ${shapeKindLabel}`,
  );
  const initialComment = $derived<string>(
    isSticky
      ? context.annotation.object.contents ?? ""
      : (context.annotation.object.custom as { comment?: string } | undefined)?.comment ?? "",
  );

  /* Local draft. Reset whenever the *selected annotation* changes —
   * we key on the annotation id so switching between highlights
   * doesn't bleed the prior draft. */
  let draft = $state("");
  let lastSeenId = $state<string | null>(null);
  let textareaEl = $state<HTMLTextAreaElement | undefined>(undefined);
  $effect(() => {
    const id = context.annotation.object.id;
    if (id !== lastSeenId) {
      lastSeenId = id;
      draft = initialComment;
      /* Auto-focus so the user can start typing immediately; cursor at
       * end so "add to existing comment" just works. */
      queueMicrotask(() => {
        const el = textareaEl;
        if (!el) return;
        el.focus();
        const n = el.value.length;
        try {
          el.setSelectionRange(n, n);
        } catch {
          /* selection-range unsupported in some edge cases — ignore */
        }
      });
    }
  });

  function commitIfChanged() {
    const annProv = annotation.provides;
    if (!annProv || context.structurallyLocked) return;
    const trimmed = draft.trim();
    if (trimmed === initialComment.trim()) return;
    const pageIndex = context.pageIndex;
    const id = context.annotation.object.id;
    if (isSticky) {
      /* TEXT sticky note: contents IS the note body. */
      annProv.updateAnnotation(pageIndex, id, {
        contents: trimmed,
        modified: new Date(),
      });
    } else {
      /* Highlight: comment goes under custom.comment; contents holds
       * the excerpt and stays untouched here. */
      const prev = (context.annotation.object.custom ?? {}) as Record<string, unknown>;
      const nextCustom: Record<string, unknown> = { ...prev };
      if (trimmed) nextCustom.comment = trimmed;
      else delete nextCustom.comment;
      annProv.updateAnnotation(pageIndex, id, {
        custom: Object.keys(nextCustom).length > 0 ? nextCustom : undefined,
        modified: new Date(),
      });
    }
  }

  /* Escape "gets out" of the popover entirely:
   *   - revert the draft (don't commit half-typed text)
   *   - blur the textarea + deselect the annotation (closes this menu)
   *   - deactivate any active tool (so the user isn't still in
   *     sticky-note placement mode and dropping notes on the next
   *     click — closes the loop for "I'm done annotating right now")
   * We listen at the window level so Escape works whether focus is in
   * the textarea or somewhere else in the popover. */
  function escape() {
    draft = initialComment;
    textareaEl?.blur();
    annotation.provides?.deselectAnnotation();
    annotation.provides?.setActiveTool(null);
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey && !e.metaKey && !e.ctrlKey && !e.altKey) {
      e.preventDefault();
      commitIfChanged();
      textareaEl?.blur();
      annotation.provides?.deselectAnnotation();
    }
    /* Escape is handled at the window level below; left here only to
     * absorb the textarea's default behaviour. */
  }

  $effect(() => {
    if (!selected) return;
    function onWindowKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      e.preventDefault();
      escape();
    }
    window.addEventListener("keydown", onWindowKey, { capture: true });
    return () => window.removeEventListener("keydown", onWindowKey, { capture: true });
  });

  function remove() {
    const annProv = annotation.provides;
    if (!annProv || context.structurallyLocked) return;
    annProv.deleteAnnotation(context.pageIndex, context.annotation.object.id);
  }
</script>

<span style={menuWrapperProps.style} use:menuWrapperProps.action>
  {#if selected && !context.structurallyLocked}
    <div
      class="ann-menu"
      style:position="absolute"
      style:top="{rect.size.height + 8}px"
      style:left="50%"
      style:transform="translateX(-50%)"
      style:z-index="1000"
      style:cursor="default"
    >
      {#if isBookmark}
        <div class="bookmark-label">📌 Bookmark</div>
        <div class="actions">
          <button
            type="button"
            class="del"
            onclick={remove}
            title="Remove the bookmark"
            aria-label="Remove the bookmark"
          >
            Remove bookmark
          </button>
        </div>
      {:else}
        {#if excerpt}
          <div class="excerpt" title={excerpt}>“{excerpt}”</div>
        {/if}
        <textarea
          class="comment"
          placeholder={isSticky
            ? "Write a note…  (Enter to save, Shift+Enter for newline)"
            : "Add a comment…  (Enter to save, Shift+Enter for newline)"}
          rows="2"
          bind:value={draft}
          bind:this={textareaEl}
          onblur={commitIfChanged}
          onkeydown={onKeydown}
        ></textarea>
        <div class="actions">
          <button
            type="button"
            class="del"
            onclick={remove}
            title={deleteLabel}
            aria-label={deleteLabel}
          >
            {deleteLabel}
          </button>
        </div>
      {/if}
    </div>
  {/if}
</span>

<style>
  .ann-menu {
    pointer-events: auto;
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 8px 10px;
    width: 280px;
    border-radius: 6px;
    background: var(--panel, #fff);
    border: 1px solid var(--ink-12, rgba(26, 22, 18, 0.18));
    box-shadow:
      0 2px 0 rgba(0, 0, 0, 0.02),
      0 8px 20px -8px rgba(26, 22, 18, 0.28);
  }
  .excerpt {
    font-size: 11px;
    font-style: italic;
    color: var(--ink-50, rgba(26, 22, 18, 0.62));
    line-height: 1.35;
    max-height: 3.6em;
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
  }
  .bookmark-label {
    font-family: var(--sans, Inter, system-ui, sans-serif);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.4px;
    text-transform: uppercase;
    color: var(--accent, #7a3a14);
    padding: 2px 0;
  }
  .comment {
    appearance: none;
    width: 100%;
    box-sizing: border-box;
    resize: vertical;
    min-height: 44px;
    max-height: 200px;
    font: inherit;
    font-size: 12px;
    line-height: 1.4;
    color: var(--ink, #1a1612);
    background: var(--surface, #fff);
    border: 1px solid var(--ink-12, rgba(26, 22, 18, 0.18));
    border-radius: 4px;
    padding: 6px 8px;
  }
  .comment:focus-visible {
    outline: 2px solid var(--accent, #7a3a14);
    outline-offset: 0;
    border-color: var(--accent, #7a3a14);
  }
  .actions {
    display: flex;
    justify-content: flex-end;
  }
  .del {
    appearance: none;
    border: none;
    background: transparent;
    color: var(--ink-50, rgba(26, 22, 18, 0.55));
    font: inherit;
    font-size: 11px;
    padding: 2px 6px;
    border-radius: 4px;
    cursor: pointer;
    text-decoration: underline;
    text-decoration-color: var(--ink-12, rgba(26, 22, 18, 0.22));
    text-underline-offset: 2px;
  }
  .del:hover {
    color: #b03020;
    text-decoration-color: #b03020;
    background: transparent;
  }
  .del:focus-visible {
    outline: 2px solid #b03020;
    outline-offset: 2px;
  }
</style>

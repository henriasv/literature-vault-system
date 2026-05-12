<!--
  Popover that appears when an existing annotation is selected. Mirrors
  the text-selection menu's shape (same MenuWrapperProps contract) so
  EmbedPDF can position it.

  For highlights: shows the captured excerpt (read-only, from
  `contents`) and a textarea bound to the user's freeform comment,
  stored on the annotation under `custom.comment`. The PDF spec
  reserves `custom` for non-standard payload and EmbedPDF round-trips
  it through import/export untouched, so the comment lives alongside
  the annotation in `Annotations/{citekey}.json` instead of leaking
  into the .md note.

  Enter saves and closes the menu (commits + deselects); Shift+Enter
  inserts a newline; Esc reverts the draft. Saving also runs on blur
  as a safety net. Delete is styled as the secondary/destructive
  escape hatch.
-->
<script lang="ts">
  import { useAnnotationCapability } from "@embedpdf/plugin-annotation/svelte";
  import type { MenuWrapperProps } from "@embedpdf/utils/svelte";
  import type { Rect } from "@embedpdf/models";
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

  const excerpt = $derived<string>(context.annotation.object.contents ?? "");
  const initialComment = $derived<string>(
    (context.annotation.object.custom as { comment?: string } | undefined)?.comment ?? "",
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
    const prev = (context.annotation.object.custom ?? {}) as Record<string, unknown>;
    const nextCustom: Record<string, unknown> = { ...prev };
    if (trimmed) nextCustom.comment = trimmed;
    else delete nextCustom.comment;
    annProv.updateAnnotation(context.pageIndex, context.annotation.object.id, {
      custom: Object.keys(nextCustom).length > 0 ? nextCustom : undefined,
      modified: new Date(),
    });
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey && !e.metaKey && !e.ctrlKey && !e.altKey) {
      e.preventDefault();
      commitIfChanged();
      (e.currentTarget as HTMLTextAreaElement).blur();
      annotation.provides?.deselectAnnotation();
    } else if (e.key === "Escape") {
      e.preventDefault();
      draft = initialComment;
      (e.currentTarget as HTMLTextAreaElement).blur();
      annotation.provides?.deselectAnnotation();
    }
  }

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
      {#if excerpt}
        <div class="excerpt" title={excerpt}>“{excerpt}”</div>
      {/if}
      <textarea
        class="comment"
        placeholder="Add a comment…  (Enter to save, Shift+Enter for newline)"
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
          title="Delete this highlight"
          aria-label="Delete this highlight"
        >
          Delete highlight
        </button>
      </div>
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

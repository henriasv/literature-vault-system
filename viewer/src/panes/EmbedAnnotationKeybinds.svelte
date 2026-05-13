<!--
  Global keyboard shortcuts for the annotation layer. Lives inside the EmbedPDF
  tree so it can access the annotation capability via context. Currently just
  Delete/Backspace → remove the selected annotation; extend here when we add
  more shortcuts (e.g. cmd-c to copy the highlighted text).

  We use the per-document `useAnnotation` hook (not the unbound
  `useAnnotationCapability`) so we read selection straight from the active
  document's state. The non-bound capability's `getSelectedAnnotation()`
  occasionally returns null even when a selection exists (it relies on an
  active-document lookup that hasn't always resolved by the time Backspace
  fires).
-->
<script lang="ts">
  import { useAnnotation } from "@embedpdf/plugin-annotation/svelte";

  type Props = { documentId: string };
  let { documentId }: Props = $props();

  const annotation = useAnnotation(() => documentId);

  $effect(() => {
    function onKeydown(e: KeyboardEvent) {
      if (e.key !== "Delete" && e.key !== "Backspace") return;
      const target = e.target as HTMLElement | null;
      /* Don't steal Backspace from text inputs / contenteditables — the note
       * editor and search box are in the same window. */
      if (target && (target.matches("input, textarea, [contenteditable=true]") ||
                     target.isContentEditable)) return;
      const annProv = annotation.provides;
      if (!annProv) return;
      /* Read selection straight off the document state proxy instead of
       * the capability's `getSelectedAnnotation()` shortcut — the proxy
       * is always up-to-date with the latest store dispatch, the
       * shortcut can resolve to null while the state still says
       * selected. */
      const ids = annotation.state.selectedUids ?? [];
      if (ids.length === 0) return;
      e.preventDefault();
      for (const id of ids) {
        const t = annProv.getAnnotationById?.(id);
        if (t) annProv.deleteAnnotation(t.object.pageIndex, t.object.id);
      }
    }
    window.addEventListener("keydown", onKeydown);
    return () => window.removeEventListener("keydown", onKeydown);
  });
</script>

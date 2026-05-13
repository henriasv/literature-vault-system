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
      /* Read selection straight off the document state.
       *
       * Two sources, tried in order:
       *   1. the reactive proxy from `useAnnotation` (the synchronous
       *      mirror of the document store);
       *   2. a direct `getState()` call on the doc-bound provides, in
       *      case the proxy hasn't caught the latest reducer dispatch
       *      (the bundled annotation plugin's onStateChange fires async
       *      for some events).
       * Either source returns the same selectedUids list; we just need
       * one of them to have it. */
      const proxyUids: string[] = annotation.state?.selectedUids ?? [];
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const directState = (annProv as any).getState?.();
      const directUids: string[] = directState?.selectedUids ?? [];
      const uids = proxyUids.length > 0 ? proxyUids : directUids;
      if (uids.length === 0) {
        console.debug("[annotation-keybind] Backspace pressed but no annotation selected", {
          proxyUids, directUids, target,
        });
        return;
      }
      e.preventDefault();
      for (const uid of uids) {
        const t = annProv.getAnnotationById?.(uid);
        if (!t) {
          console.warn("[annotation-keybind] selected uid has no annotation", uid);
          continue;
        }
        annProv.deleteAnnotation(t.object.pageIndex, t.object.id);
      }
    }
    window.addEventListener("keydown", onKeydown);
    return () => window.removeEventListener("keydown", onKeydown);
  });
</script>

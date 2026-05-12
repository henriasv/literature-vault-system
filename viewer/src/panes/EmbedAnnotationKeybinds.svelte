<!--
  Global keyboard shortcuts for the annotation layer. Lives inside the EmbedPDF
  tree so it can access the annotation capability via context. Currently just
  Delete/Backspace → remove the selected annotation; extend here when we add
  more shortcuts (e.g. cmd-c to copy the highlighted text).
-->
<script lang="ts">
  import { useAnnotationCapability } from "@embedpdf/plugin-annotation/svelte";

  const annotation = useAnnotationCapability();

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
      const selected = annProv.getSelectedAnnotation();
      if (!selected) return;
      e.preventDefault();
      annProv.deleteAnnotation(selected.object.pageIndex, selected.object.id);
    }
    window.addEventListener("keydown", onKeydown);
    return () => window.removeEventListener("keydown", onKeydown);
  });
</script>

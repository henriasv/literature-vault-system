<!--
  Wire ⌘C / Ctrl-C to the EmbedPDF selection plugin's
  `copyToClipboard()` so users can copy selected text from a PDF.

  The plugin already exposes `onCopyToClipboard` events and a
  `copyToClipboard(documentId)` action, but it does NOT install its
  own keyboard listener. Without one, ⌘C falls through to the
  browser's default copy — and the PDF "selection" is a virtual
  overlay (not a real DOM Selection), so nothing ends up on the
  clipboard.

  Mount this once inside the <EmbedPDF> children snippet so it sits in
  the plugin context. It bails when the focused element is editable
  (CodeMirror, <input>, <textarea>, contenteditable) so the editor's
  own ⌘C is untouched.
-->
<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { useSelectionCapability } from "@embedpdf/plugin-selection/svelte";

  let { documentId }: { documentId: string } = $props();

  const selection = useSelectionCapability();

  function isEditableTarget(t: EventTarget | null): boolean {
    if (!(t instanceof HTMLElement)) return false;
    const tag = t.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
    if (t.isContentEditable) return true;
    if (t.closest(".cm-content")) return true; // CodeMirror editor
    return false;
  }

  function onKeyDown(e: KeyboardEvent) {
    if (!(e.metaKey || e.ctrlKey) || e.shiftKey || e.altKey) return;
    if (e.key !== "c" && e.key !== "C") return;
    if (isEditableTarget(e.target)) return; // let the editor copy its own selection
    const provides = selection.provides;
    if (!provides) return;
    const text = provides.getSelectedText(documentId);
    if (!text || (Array.isArray(text) ? text.join("").trim() === "" : String(text).trim() === "")) {
      /* No PDF selection — let the browser have ⌘C. */
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    provides.copyToClipboard(documentId);
  }

  onMount(() => {
    /* Capture phase so we land before any in-DOM handler (e.g. the
     * selection layer's own pointer plumbing) — only matters when the
     * focus is on the PDF area, where there'd otherwise be no copy
     * handler at all. */
    window.addEventListener("keydown", onKeyDown, { capture: true });
  });

  onDestroy(() => {
    window.removeEventListener("keydown", onKeyDown, { capture: true } as EventListenerOptions);
  });
</script>

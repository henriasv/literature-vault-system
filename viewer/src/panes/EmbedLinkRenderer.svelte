<!--
  Custom renderer for PDF LINK annotations.

  EmbedPDF's bundled LinkLockedMode component wires its click handler via
  the old Svelte delegation (`div.__click = …`) which Svelte 5.55 doesn't
  dispatch — so on this codebase clicking a link in the PDF does
  nothing. Replace it with a normal `onclick` binding and route the
  navigation ourselves:

    - Internal destinations / Goto actions → annotation plugin's
      `navigateTarget(target)` (scrolls to the page).
    - URI actions → hand off to the OS via the `open_path_external`
      Tauri command so the URL opens in the default browser (in Tauri
      `window.open` is restricted; routing through the OS is the
      reliable path).
-->
<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { useAnnotationCapability } from "@embedpdf/plugin-annotation/svelte";
  import { toast } from "../state/toast.svelte";

  /* The annotation plugin uses `PdfActionType.URI = 3`. We pin the
   * literal here rather than importing the enum so this renderer can
   * stay independent of @embedpdf/models specifics. */
  const ACTION_TYPE_URI = 3;

  type LinkTarget =
    | { type: "action"; action: { type: number; uri?: string; destination?: unknown } }
    | { type: "destination"; destination: unknown }
    | undefined;

  type AnnObj = {
    id: string;
    pageIndex: number;
    target?: LinkTarget;
  };

  type Props = {
    annotation: { object: AnnObj };
    currentObject: AnnObj;
    isSelected: boolean;
    isEditing: boolean;
    scale: number;
    pageIndex: number;
    documentId: string;
    onClick?: (e: PointerEvent | MouseEvent) => void;
    appearanceActive?: boolean;
  };
  let { annotation, currentObject, documentId, appearanceActive = false }: Props = $props();

  const ann = useAnnotationCapability();

  function handleClick(e: MouseEvent | KeyboardEvent) {
    e.preventDefault();
    e.stopPropagation();
    const target = currentObject.target ?? annotation.object.target;
    if (!target) return;
    if (
      target.type === "action" &&
      target.action.type === ACTION_TYPE_URI &&
      typeof target.action.uri === "string" &&
      target.action.uri.length > 0
    ) {
      void (async () => {
        try {
          await invoke("open_path_external", { path: target.action.uri });
        } catch (err) {
          toast(`Open link failed: ${err}`, "error");
        }
      })();
      return;
    }
    /* Internal navigation (goto / destination) — let the plugin handle it. */
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ann.provides?.forDocument(documentId).navigateTarget(target as any);
    } catch (err) {
      console.warn("[link] navigateTarget failed", err);
    }
  }
</script>

<div
  class="link-host"
  role="link"
  tabindex="-1"
  style:position="absolute"
  style:inset="0"
  style:width="100%"
  style:height="100%"
  style:cursor="pointer"
  style:pointer-events="auto"
  style:opacity={appearanceActive ? 0 : 1}
  onclick={handleClick}
  onkeydown={(e) => { if (e.key === "Enter") handleClick(e); }}>
  <!-- Same subtle blue underline cue the bundled renderer used, so
       hyperlinks still read as hyperlinks visually. -->
</div>

<style>
  .link-host {
    /* Hover hint: dotted underline-ish accent under the link rect. */
    border-bottom: 1px solid transparent;
    transition: border-color 80ms ease;
  }
  .link-host:hover {
    border-bottom-color: rgba(122, 58, 20, 0.4);
    background-color: rgba(122, 58, 20, 0.06);
  }
</style>

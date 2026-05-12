<!--
  Popover that appears when an existing annotation is selected. Mirrors the
  text-selection menu's shape (same MenuWrapperProps contract) so EmbedPDF can
  position it. For now: just a delete button. We can grow this into a
  color-picker / lock toggle when we need them.
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
      <button type="button" class="del" onclick={remove} title="Delete highlight" aria-label="Delete highlight">
        Delete
      </button>
    </div>
  {/if}
</span>

<style>
  .ann-menu {
    pointer-events: auto;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 6px;
    border-radius: 6px;
    background: var(--panel, #fff);
    border: 1px solid var(--ink-12, rgba(26, 22, 18, 0.18));
    box-shadow:
      0 2px 0 rgba(0, 0, 0, 0.02),
      0 8px 20px -8px rgba(26, 22, 18, 0.28);
  }
  .del {
    appearance: none;
    border: none;
    background: transparent;
    color: var(--ink, #1a1612);
    font: inherit;
    font-size: 12px;
    padding: 4px 8px;
    border-radius: 4px;
    cursor: pointer;
  }
  .del:hover {
    background: var(--ink-08, rgba(26, 22, 18, 0.08));
  }
  .del:focus-visible {
    outline: 2px solid var(--accent, #7a3a14);
    outline-offset: 2px;
  }
</style>

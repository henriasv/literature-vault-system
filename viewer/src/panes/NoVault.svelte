<!--
  NoVault — shown as the entire main pane when no active vault is configured.

  Visual scaffolding only at this turn. Wiring into App.svelte happens when the
  active-vault persistence layer lands (next turn): if no vault path is set,
  render <NoVault /> as the full-window content with the same two actions the
  File menu offers.

  Buttons emit callbacks rather than calling the picker themselves so App.svelte
  stays the single source of truth for vault-bootstrap orchestration.
-->
<script lang="ts">
  type Props = {
    onOpen: () => void;
    onNew: () => void;
  };
  let { onOpen, onNew }: Props = $props();
</script>

<section class="nv-root">
  <div class="nv-card" data-tauri-drag-region>
    <p class="caps nv-eyebrow">Literature Vault</p>
    <h1 class="nv-title">
      Welcome.
    </h1>
    <p class="nv-lede">
      A reference manager system for the BibTeX + Markdown workflow.
      To get started, point the Viewer at a vault — or create one.
    </p>

    <div class="nv-actions">
      <button type="button" class="nv-btn primary" onclick={onOpen}>
        Open existing vault…
      </button>
      <button type="button" class="nv-btn ghost" onclick={onNew}>
        New vault…
      </button>
    </div>

    <p class="nv-fineprint">
      A vault is just a folder on disk: <span class="mono">PaperNotes/</span>,
      <span class="mono">Bibfiles/</span>, <span class="mono">PDFs/</span>,
      <span class="mono">index.json</span>, <span class="mono">library.bib</span>.
      You can also point the Viewer at one via the
      <span class="mono">LITERATURE_VAULT_ROOT</span> environment variable.
    </p>
  </div>
</section>

<style>
  .nv-root {
    position: fixed;
    inset: 0;
    background: var(--recess, #e6dfc8);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 48px 32px;
  }
  .nv-card {
    max-width: 560px;
    width: 100%;
    background: var(--panel, #fff);
    border: 1px solid var(--ink-12, rgba(26, 22, 18, 0.12));
    border-radius: 6px;
    padding: 44px 44px 36px;
    box-shadow:
      0 1px 0 rgba(0, 0, 0, 0.02),
      0 18px 40px -18px rgba(26, 22, 18, 0.16);
  }
  .nv-eyebrow {
    color: var(--accent, #7a3a14);
    margin: 0 0 14px;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    font-weight: 600;
  }
  .nv-title {
    font-family: var(--serif, "Source Serif 4", "Hoefler Text", Georgia, serif);
    font-weight: 700;
    font-size: clamp(2rem, 4vw, 2.75rem);
    line-height: 1.08;
    letter-spacing: -0.012em;
    margin: 0 0 18px;
    color: var(--ink, #1a1612);
  }
  .nv-lede {
    font-family: var(--serif, "Source Serif 4", "Hoefler Text", Georgia, serif);
    font-size: 17px;
    line-height: 1.5;
    color: var(--ink, #1a1612);
    margin: 0 0 28px;
  }
  .nv-actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    margin-bottom: 28px;
  }
  .nv-btn {
    font: inherit;
    font-size: 14px;
    font-weight: 500;
    padding: 9px 16px;
    border-radius: 3px;
    border: 1px solid var(--accent, #7a3a14);
    cursor: pointer;
    transition: background 0.12s ease;
  }
  .nv-btn.primary {
    background: var(--accent, #7a3a14);
    color: #fdf6e8;
  }
  .nv-btn.primary:hover {
    background: var(--accent-bright, #b03020);
    border-color: var(--accent-bright, #b03020);
  }
  .nv-btn.ghost {
    background: transparent;
    color: var(--accent, #7a3a14);
  }
  .nv-btn.ghost:hover {
    background: rgba(122, 58, 20, 0.08);
  }
  .nv-fineprint {
    font-family: var(--serif, "Source Serif 4", Georgia, serif);
    font-size: 13px;
    line-height: 1.55;
    color: var(--ink-70, rgba(26, 22, 18, 0.7));
    margin: 0;
    padding-top: 20px;
    border-top: 1px solid var(--ink-07, rgba(26, 22, 18, 0.07));
  }
  .mono {
    font-family: "JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace;
    font-size: 0.92em;
    color: var(--ink, #1a1612);
  }
</style>

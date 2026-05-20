<script lang="ts">
  /**
   * Post-drop metadata sheet for review filings.
   *
   * Opens automatically right after the user drops PDFs onto a review
   * project. Lists each just-filed paper with editable Title + Authors
   * fields (authors are entered as a comma-separated string). "Save"
   * commits via the Rust `update_review_meta` command; "Skip" closes
   * without changes (filename-derived defaults persist).
   */
  import { invoke } from "@tauri-apps/api/core";
  import { reviewMetaEditState, closeReviewMetaSheet } from "../state/reviewMetaEdit.svelte";
  import { refreshReviewProjects } from "../state/review.svelte";
  import { toast } from "../state/toast.svelte";

  let saving = $state(false);

  function parseAuthors(s: string): string[] {
    return s
      .split(",")
      .map((a) => a.trim())
      .filter((a) => a.length > 0);
  }

  async function saveAll() {
    if (saving) return;
    saving = true;
    let errors = 0;
    try {
      for (const draft of reviewMetaEditState.drafts) {
        try {
          await invoke("update_review_meta", {
            citekey: draft.citekey,
            title: draft.title.trim(),
            authors: parseAuthors(draft.authors),
          });
        } catch (e) {
          errors += 1;
          console.warn("update_review_meta failed", draft.citekey, e);
        }
      }
      if (errors === 0) {
        toast(`Saved metadata for ${reviewMetaEditState.drafts.length} paper${reviewMetaEditState.drafts.length === 1 ? "" : "s"}`);
      } else {
        toast(`Saved with ${errors} error${errors === 1 ? "" : "s"} — see console`, "error");
      }
      closeReviewMetaSheet();
      void refreshReviewProjects();
    } finally {
      saving = false;
    }
  }

  function skip() {
    closeReviewMetaSheet();
  }

  function onBackdropKey(e: KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      skip();
    }
  }
</script>

{#if reviewMetaEditState.drafts.length > 0}
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <div class="backdrop" role="dialog" aria-modal="true" aria-label="Edit review paper metadata" onkeydown={onBackdropKey} tabindex="-1">
    <div class="sheet">
      <header>
        <h2>Just filed</h2>
        <p>
          {reviewMetaEditState.drafts.length} paper{reviewMetaEditState.drafts.length === 1 ? "" : "s"} ·
          edit title / authors now, or skip and edit later.
        </p>
      </header>

      <div class="rows">
        {#each reviewMetaEditState.drafts as draft (draft.citekey)}
          <section class="row">
            <div class="src">{draft.sourceName}</div>
            <label>
              <span class="caps">Title</span>
              <input type="text" bind:value={draft.title} placeholder="Title" />
            </label>
            <label>
              <span class="caps">Authors <span class="hint">comma-separated</span></span>
              <input type="text" bind:value={draft.authors} placeholder="Lastname, F., Lastname, F." />
            </label>
          </section>
        {/each}
      </div>

      <footer>
        <button class="btn ghost" onclick={skip} disabled={saving}>Skip</button>
        <button class="btn primary" onclick={saveAll} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </button>
      </footer>
    </div>
  </div>
{/if}

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.35);
    backdrop-filter: blur(2px);
    z-index: 950;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .sheet {
    width: min(620px, 90vw);
    max-height: 80vh;
    display: flex;
    flex-direction: column;
    background: var(--panel);
    border: 1px solid var(--ink);
    box-shadow: 0 24px 48px -12px rgba(26, 22, 18, 0.4);
    font-family: var(--sans);
    color: var(--fg);
  }
  header {
    padding: 18px 22px 12px;
    border-bottom: 1px solid var(--ink-12);
  }
  header h2 {
    margin: 0 0 4px;
    font-family: var(--sans);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--accent);
  }
  header p {
    margin: 0;
    font-family: var(--mono);
    font-size: 10.5px;
    letter-spacing: 0.3px;
    color: var(--ink-50);
  }

  .rows {
    flex: 1 1 auto;
    overflow-y: auto;
    padding: 8px 22px 12px;
  }
  .row {
    padding: 12px 0;
    border-bottom: 1px solid var(--ink-12);
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .row:last-child { border-bottom: 0; }
  .row .src {
    font-family: var(--mono);
    font-size: 10px;
    letter-spacing: 0.3px;
    color: var(--ink-30);
    text-transform: uppercase;
  }
  .row label {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .caps {
    font-family: var(--sans);
    font-size: 9.5px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--ink-70);
    display: flex;
    align-items: baseline;
    gap: 8px;
  }
  .caps .hint {
    font-family: var(--mono);
    font-size: 9px;
    letter-spacing: 0.3px;
    text-transform: uppercase;
    color: var(--ink-30);
    font-weight: 400;
  }
  .row input[type="text"] {
    padding: 6px 10px;
    border: 1px solid var(--ink);
    background: var(--panel);
    color: var(--fg);
    font-family: var(--serif);
    font-size: 13px;
  }
  .row input[type="text"]:focus {
    outline: 1px solid var(--accent);
    outline-offset: -2px;
  }

  footer {
    padding: 12px 22px;
    border-top: 1px solid var(--ink-12);
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }
  .btn {
    padding: 6px 14px;
    font-family: var(--sans);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    border: 1px solid var(--ink);
    background: transparent;
    color: var(--ink);
    cursor: pointer;
  }
  .btn:disabled { opacity: 0.5; cursor: default; }
  .btn.ghost:hover:not(:disabled) { background: var(--hover); }
  .btn.primary { background: var(--ink); color: var(--panel); }
  .btn.primary:hover:not(:disabled) { background: var(--accent); border-color: var(--accent); }
</style>

<script lang="ts">
  /**
   * Reviewing-mode workspace.
   *
   * Two-column overlay (project tree | papers in the selected project).
   * Drop targets are wired with `data-drop-target-slug="review:<slug>"` so
   * the App-level drag-drop dispatcher (App.svelte) routes file drops to
   * `dropToReviewProject` instead of the regular library filing flow.
   *
   * The visual shell mirrors CollectionsPanel so the ViewSwitch lands at
   * the same screen (x, y) when flipping between Reading / Organizing /
   * Reviewing.
   */
  import { onMount } from "svelte";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import { openInTab } from "../state/tabs.svelte";
  import { toast } from "../state/toast.svelte";
  import { prefsState } from "../state/prefs.svelte";
  import {
    reviewState,
    refreshReviewProjects,
    selectReviewProject,
    createReviewProjectFlow,
  } from "../state/review.svelte";
  import { dndState } from "../state/dnd.svelte";
  import ViewSwitch from "./ViewSwitch.svelte";

  onMount(() => {
    void refreshReviewProjects();
  });

  /** Same as CollectionsPanel: this strip is the window drag region but
   *  we have to start the OS drag ourselves because `data-tauri-drag-region`
   *  isn't reliably consumed under `dragDropEnabled: true`. */
  function onStripMouseDown(e: MouseEvent): void {
    if (e.button !== 0) return;
    const t = e.target as HTMLElement;
    if (t.closest('button, a, input, textarea, [role="button"], [role="tab"]')) return;
    e.preventDefault();
    getCurrentWindow()
      .startDragging()
      .catch((err) => console.error("startDragging (review strip) failed:", err));
  }

  let creating = $state(false);
  let newSlug = $state("");
  let creatingInputEl = $state<HTMLInputElement | undefined>(undefined);

  async function commitNewProject(): Promise<void> {
    const slug = newSlug.trim();
    if (!slug) {
      creating = false;
      return;
    }
    try {
      const created = await createReviewProjectFlow(slug);
      newSlug = "";
      creating = false;
      void selectReviewProject(created);
    } catch (e) {
      toast(`Create project failed: ${e}`, "error");
    }
  }

  function cancelNewProject(): void {
    creating = false;
    newSlug = "";
  }

  $effect(() => {
    if (creating && creatingInputEl) {
      creatingInputEl.focus();
    }
  });

  function pickProject(slug: string): void {
    void selectReviewProject(slug);
  }

  function openPaper(citekey: string): void {
    openInTab(citekey);
    prefsState.viewMode = "reading";
  }

  /* Drop-target highlight for the currently hovered review project, wired
   * by the App-level drag-drop dispatcher via the shared dndState. */
  const hoveredSlug = $derived(dndState.hoverSlug);
</script>

<section class="review">
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="top-strip"
    data-tauri-drag-region
    onmousedown={onStripMouseDown}>
    <ViewSwitch active="review" />
    <div class="strip-spacer"></div>
    <span class="top-meta">
      {reviewState.projects.length} project{reviewState.projects.length === 1 ? "" : "s"}
    </span>
  </div>

  <div class="columns">
    <aside class="projects-pane">
      <div class="pane-head">
        <div class="caps">Projects</div>
        {#if !creating}
          <button class="add-btn" onclick={() => (creating = true)} title="Create a new review project">+ New</button>
        {/if}
      </div>

      {#if creating}
        <div class="new-row">
          <input
            class="new-input"
            type="text"
            placeholder="e.g. hon2200_v26_project2"
            bind:value={newSlug}
            bind:this={creatingInputEl}
            onkeydown={(e) => {
              if (e.key === "Enter") { e.preventDefault(); void commitNewProject(); }
              if (e.key === "Escape") { e.preventDefault(); cancelNewProject(); }
            }}
          />
          <button class="new-ok" onclick={() => void commitNewProject()}>Create</button>
          <button class="new-cancel" onclick={cancelNewProject}>Cancel</button>
        </div>
      {/if}

      <div class="tree-scroll">
        {#if reviewState.projects.length === 0 && !creating}
          <div class="empty">
            <p>No review projects yet.</p>
            <p class="hint">Create one with <strong>+ New</strong> above, then drag PDFs onto it.</p>
          </div>
        {/if}
        {#each reviewState.projects as project (project.slug)}
          <button
            class="proj-row"
            class:active={reviewState.selectedProject === project.slug}
            class:drop-hover={hoveredSlug === `review:${project.slug}`}
            data-drop-target-slug={`review:${project.slug}`}
            onclick={() => pickProject(project.slug)}>
            <span class="proj-name">{project.slug}</span>
            <span class="proj-count">{project.paperCount}</span>
          </button>
        {/each}
      </div>
    </aside>

    <div class="papers-pane">
      {#if !reviewState.selectedProject}
        <div class="empty-papers">
          <h3>Select a project</h3>
          <p>Pick a project on the left to see its papers, or drop PDFs onto a project to file them.</p>
        </div>
      {:else if reviewState.loading}
        <div class="empty-papers"><p>Loading…</p></div>
      {:else if reviewState.papers.length === 0}
        <div class="empty-papers">
          <h3>{reviewState.selectedProject}</h3>
          <p>No papers yet. Drag PDFs onto this project to start.</p>
        </div>
      {:else}
        <div class="papers-head">
          <div class="caps">{reviewState.selectedProject}</div>
          <span class="hint">{reviewState.papers.length} paper{reviewState.papers.length === 1 ? "" : "s"}</span>
        </div>
        <ul class="papers-list">
          {#each reviewState.papers as p (p.citekey)}
            <li>
              <button class="paper-row" ondblclick={() => openPaper(p.citekey)} onclick={() => openPaper(p.citekey)}>
                <span class="title">{p.title || p.citekey}</span>
                {#if p.authors.length > 0}
                  <span class="sub">{p.authors[0]}{p.authors.length > 1 ? " +" + (p.authors.length - 1) : ""}</span>
                {/if}
              </button>
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  </div>
</section>

<style>
  .review {
    display: flex;
    flex-direction: column;
    height: 100%;
    background: var(--panel);
    color: var(--fg);
    font-family: var(--sans);
  }

  /* Top strip — same shape as CollectionsPanel so the ViewSwitch lands
     on the same (x, y) when flipping between Reading / Organizing /
     Reviewing. Window drag via JS startDragging() (mirrors the same
     workaround used by CollectionsPanel). */
  .top-strip {
    flex: 0 0 auto;
    height: 56px;
    padding: 0 22px 0 var(--tl-pad);
    display: flex;
    align-items: center;
    gap: 14px;
    border-bottom: 1px solid var(--ink-12);
    background: var(--panel);
    -webkit-app-region: drag;
  }
  .top-strip > * { -webkit-app-region: no-drag; }
  .strip-spacer { flex: 1; }
  .top-meta {
    font-family: var(--mono);
    font-size: 10px;
    color: var(--ink-50);
    letter-spacing: 0.4px;
    text-transform: uppercase;
  }

  .columns {
    flex: 1 1 auto;
    min-height: 0;
    display: grid;
    grid-template-columns: 340px 1fr;
  }

  /* ----- projects pane (left) ------------------------------------- */
  .projects-pane {
    display: flex;
    flex-direction: column;
    background: var(--panel);
    border-right: 1px solid var(--ink-12);
    min-width: 0;
    min-height: 0;
    overflow: hidden;
    user-select: none;
    -webkit-user-select: none;
  }
  .pane-head {
    flex: 0 0 auto;
    padding: 14px 22px 6px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  .caps {
    font-family: var(--sans);
    font-size: 9.5px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--accent);
  }
  .add-btn {
    font-family: var(--sans);
    font-size: 9.5px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    padding: 4px 10px;
    border: 1px solid var(--ink);
    background: transparent;
    color: var(--ink);
    cursor: pointer;
  }
  .add-btn:hover { background: var(--ink); color: var(--panel); }

  .new-row {
    padding: 8px 22px 12px;
    display: flex;
    gap: 6px;
    align-items: center;
  }
  .new-input {
    flex: 1;
    min-width: 0;
    padding: 4px 8px;
    border: 1px solid var(--ink);
    background: var(--panel);
    color: var(--fg);
    font-family: var(--mono);
    font-size: 11px;
  }
  .new-input:focus {
    outline: 1px solid var(--accent);
    outline-offset: -2px;
  }
  .new-ok, .new-cancel {
    padding: 4px 8px;
    font-family: var(--sans);
    font-size: 9.5px;
    font-weight: 700;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    border: 1px solid var(--ink);
    background: transparent;
    color: var(--ink);
    cursor: pointer;
  }
  .new-ok { background: var(--ink); color: var(--panel); }
  .new-cancel:hover { background: var(--ink); color: var(--panel); }

  .tree-scroll {
    flex: 1 1 auto;
    min-height: 0;
    overflow-y: auto;
    padding-bottom: 12px;
    display: flex;
    flex-direction: column;
    align-items: stretch;
  }

  .proj-row {
    flex: 0 0 auto;
    width: 100%;
    text-align: left;
    background: transparent;
    color: var(--fg);
    border: 0;
    border-radius: 0;
    padding: 7px 22px;
    display: flex;
    align-items: center;
    gap: 12px;
    font-family: var(--mono);
    font-size: 12px;
    cursor: pointer;
  }
  .proj-row:hover { background: var(--hover); }
  .proj-row.active {
    background: var(--accent-soft);
    color: var(--accent);
  }
  .proj-row.drop-hover {
    background: var(--drop-soft);
    outline: 1px dashed var(--accent);
    outline-offset: -1px;
  }
  .proj-name {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .proj-count {
    flex: 0 0 auto;
    font-family: var(--mono);
    font-size: 10px;
    color: var(--ink-50);
    letter-spacing: 0.4px;
  }
  .proj-row.active .proj-count { color: var(--accent); }

  .empty {
    padding: 18px 22px;
    color: var(--ink-50);
    font-size: 12px;
    line-height: 1.5;
  }
  .empty p { margin: 0 0 6px; }
  .empty .hint {
    font-family: var(--mono);
    font-size: 10px;
    letter-spacing: 0.3px;
    color: var(--ink-30);
  }

  /* ----- papers pane (right) ------------------------------------- */
  .papers-pane {
    display: flex;
    flex-direction: column;
    background: var(--panel);
    min-width: 0;
    min-height: 0;
    overflow: hidden;
  }
  .papers-head {
    flex: 0 0 auto;
    padding: 14px 24px 10px;
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
    border-bottom: 1px solid var(--ink-12);
  }
  .papers-head .caps {
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.2px;
    text-transform: none;
    color: var(--ink);
  }
  .hint {
    font-family: var(--mono);
    font-size: 9.5px;
    letter-spacing: 0.4px;
    text-transform: uppercase;
    color: var(--ink-30);
  }
  .papers-list {
    flex: 1 1 auto;
    margin: 0;
    padding: 6px 0 12px;
    list-style: none;
    overflow-y: auto;
  }
  .paper-row {
    width: 100%;
    text-align: left;
    background: transparent;
    border: 0;
    padding: 10px 24px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    cursor: pointer;
    color: var(--fg);
    font-family: var(--sans);
  }
  .paper-row:hover { background: var(--hover); }
  .paper-row .title {
    font-family: var(--serif);
    font-size: 14px;
    line-height: 1.35;
    color: var(--ink);
  }
  .paper-row .sub {
    font-family: var(--mono);
    font-size: 10.5px;
    letter-spacing: 0.2px;
    color: var(--ink-50);
  }

  .empty-papers {
    padding: 60px 32px;
    max-width: 520px;
    color: var(--ink-50);
  }
  .empty-papers h3 {
    margin: 0 0 10px 0;
    font-family: var(--sans);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--accent);
  }
  .empty-papers p {
    margin: 4px 0;
    font-size: 13px;
    line-height: 1.55;
    font-family: var(--serif);
  }
</style>

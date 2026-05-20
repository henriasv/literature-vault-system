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
    background: var(--surface);
    color: var(--fg);
    font-family: var(--sans);
  }
  .top-strip {
    flex-shrink: 0;
    height: 56px;
    padding: 14px 16px;
    display: flex;
    align-items: center;
    gap: 12px;
    border-bottom: 1px solid var(--ink-12, rgba(26, 22, 18, 0.12));
    padding-left: 84px; /* traffic-light clearance */
  }
  .strip-spacer { flex: 1; }
  .top-meta {
    font-size: 11px;
    color: var(--ink-70, rgba(26, 22, 18, 0.7));
    letter-spacing: 0.04em;
  }
  .columns {
    flex: 1;
    display: grid;
    grid-template-columns: 320px 1fr;
    min-height: 0;
  }
  .projects-pane {
    border-right: 1px solid var(--ink-12);
    display: flex;
    flex-direction: column;
    min-height: 0;
  }
  .pane-head {
    padding: 12px 14px 8px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid var(--ink-12);
  }
  .caps {
    font-size: 9.5px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--ink-70);
  }
  .add-btn {
    font-family: var(--sans);
    font-size: 9.5px;
    font-weight: 700;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    padding: 4px 10px;
    border: 1px solid var(--ink);
    background: transparent;
    color: var(--ink);
    cursor: pointer;
  }
  .add-btn:hover { background: var(--ink); color: var(--backdrop); }
  .new-row {
    padding: 10px 14px;
    display: flex;
    gap: 6px;
    border-bottom: 1px solid var(--ink-12);
  }
  .new-input {
    flex: 1;
    padding: 4px 8px;
    border: 1px solid var(--ink);
    background: var(--surface);
    color: var(--fg);
    font-family: var(--mono, ui-monospace, monospace);
    font-size: 12px;
  }
  .new-ok, .new-cancel {
    padding: 4px 8px;
    font-size: 9.5px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    border: 1px solid var(--ink);
    background: transparent;
    color: var(--ink);
    cursor: pointer;
  }
  .new-ok { background: var(--ink); color: var(--backdrop); }
  .new-cancel:hover { background: var(--ink); color: var(--backdrop); }
  .tree-scroll {
    flex: 1;
    overflow-y: auto;
    padding: 6px 0;
  }
  .proj-row {
    width: 100%;
    text-align: left;
    background: transparent;
    color: var(--fg);
    border: 0;
    padding: 7px 14px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-family: var(--mono, ui-monospace, monospace);
    font-size: 12px;
    cursor: pointer;
  }
  .proj-row:hover { background: var(--hover, rgba(26, 22, 18, 0.05)); }
  .proj-row.active { background: var(--ink); color: var(--backdrop); }
  .proj-row.drop-hover { outline: 2px dashed var(--accent, #B45F3A); outline-offset: -2px; }
  .proj-count {
    font-size: 10px;
    color: var(--ink-70);
    margin-left: 8px;
  }
  .proj-row.active .proj-count { color: var(--backdrop); }
  .empty {
    padding: 20px 14px;
    color: var(--ink-70);
    font-size: 12px;
    line-height: 1.5;
  }
  .empty .hint { font-size: 11px; margin-top: 6px; }
  .papers-pane {
    display: flex;
    flex-direction: column;
    min-height: 0;
  }
  .papers-head {
    padding: 12px 16px 8px;
    border-bottom: 1px solid var(--ink-12);
    display: flex;
    align-items: baseline;
    justify-content: space-between;
  }
  .hint { font-size: 11px; color: var(--ink-70); }
  .papers-list {
    flex: 1;
    margin: 0;
    padding: 4px 0;
    list-style: none;
    overflow-y: auto;
  }
  .paper-row {
    width: 100%;
    text-align: left;
    background: transparent;
    border: 0;
    padding: 10px 16px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    cursor: pointer;
    color: var(--fg);
  }
  .paper-row:hover { background: var(--hover, rgba(26, 22, 18, 0.05)); }
  .paper-row .title { font-size: 13px; line-height: 1.35; }
  .paper-row .sub { font-size: 11px; color: var(--ink-70); }
  .empty-papers {
    padding: 40px 24px;
    color: var(--ink-70);
    max-width: 480px;
  }
  .empty-papers h3 {
    margin: 0 0 8px 0;
    font-size: 14px;
    font-family: var(--mono, ui-monospace, monospace);
    color: var(--ink);
  }
  .empty-papers p { font-size: 12px; line-height: 1.5; margin: 6px 0; }
</style>

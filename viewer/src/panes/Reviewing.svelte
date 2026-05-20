<script lang="ts">
  /**
   * Reviewing-mode left rail. Drops into the same .lib slot as
   * Library.svelte (instead of overlaying the whole window), so flipping
   * into Reviewing keeps the PDF + NoteEditor pane visible on the right
   * and clicking a review paper opens it as a tab — exactly the Reading
   * experience, but with a project tree on the left instead of the
   * library list.
   *
   * Layout: top strip with ViewSwitch (same shape as Library so the
   * ViewSwitch lands at the same screen (x, y) when toggling), then a
   * Projects section, then a Papers section showing the papers in the
   * currently-selected project.
   */
  import { onMount } from "svelte";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import { openInTab } from "../state/tabs.svelte";
  import { toast } from "../state/toast.svelte";
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

  /* Native window-drag from a JS mousedown handler. Mirrors the same
   * workaround used by Library / CollectionsPanel — Tauri's
   * data-tauri-drag-region attribute isn't reliably consumed under
   * dragDropEnabled: true, so we start the OS drag ourselves. */
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

  /* Clicking a review paper opens it in a tab on the right pane. We do
   * NOT change viewMode — the user wants the Reviewing rail to stay
   * visible while they read the paper (same shape as Reading mode, just
   * with projects on the left instead of the library list). */
  function openPaper(citekey: string): void {
    openInTab(citekey);
  }

  /* Drop-target highlight for the currently hovered review project,
   * driven by dndState.hoverSlug (set by the App-level drag-drop
   * dispatcher during file drags). */
  const hoveredSlug = $derived(dndState.hoverSlug);
</script>

<section class="review-rail">
  <!-- Top strip — same shape (height + padding + view-switch position)
       as Library's so the cursor lands on the same (x, y) when flipping. -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="top-strip"
    data-tauri-drag-region
    onmousedown={onStripMouseDown}>
    <ViewSwitch active="review" />
  </div>

  <header class="masthead">
    <div class="caps">
      <span>Reviewing</span>
      <span class="dot">·</span>
      <span>{reviewState.projects.length} project{reviewState.projects.length === 1 ? "" : "s"}</span>
    </div>
    <h1 class="title"><span class="italic">Student work.</span></h1>
  </header>

  <!-- Projects section -->
  <div class="section-head">
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
      <button class="new-ok" onclick={() => void commitNewProject()}>OK</button>
      <button class="new-cancel" onclick={cancelNewProject}>×</button>
    </div>
  {/if}

  <div class="projects-scroll">
    {#if reviewState.projects.length === 0 && !creating}
      <div class="empty">
        <p>No review projects yet.</p>
        <p class="hint">Create one with <strong>+ New</strong>, then drag PDFs onto it.</p>
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

  <!-- Papers section — shown only when a project is selected -->
  {#if reviewState.selectedProject}
    <div class="section-head papers-head">
      <div class="caps">{reviewState.selectedProject}</div>
      <span class="hint">
        {reviewState.papers.length} paper{reviewState.papers.length === 1 ? "" : "s"}
      </span>
    </div>
    <div class="papers-scroll">
      {#if reviewState.loading}
        <div class="empty"><p class="hint">Loading…</p></div>
      {:else if reviewState.papers.length === 0}
        <div class="empty"><p class="hint">Drag PDFs onto this project to file them.</p></div>
      {:else}
        {#each reviewState.papers as p (p.citekey)}
          <button class="paper-row" ondblclick={() => openPaper(p.citekey)} onclick={() => openPaper(p.citekey)}>
            <span class="title">{p.title || p.citekey}</span>
            {#if p.authors.length > 0}
              <span class="sub">{p.authors[0]}{p.authors.length > 1 ? " +" + (p.authors.length - 1) : ""}</span>
            {/if}
          </button>
        {/each}
      {/if}
    </div>
  {/if}
</section>

<style>
  .review-rail {
    display: flex;
    flex-direction: column;
    height: 100%;
    background: var(--panel);
    color: var(--fg);
    font-family: var(--sans);
    user-select: none;
    -webkit-user-select: none;
    min-height: 0;
  }
  .top-strip {
    flex: 0 0 auto;
    height: 56px;
    padding: 0 22px 0 var(--tl-pad);
    display: flex;
    align-items: center;
    gap: 14px;
    border-bottom: 1px solid var(--ink-12);
  }

  /* Masthead — mirrors Library's masthead shape but slimmer. */
  .masthead {
    flex: 0 0 auto;
    padding: 12px 22px 8px;
    border-bottom: 1px solid var(--ink-12);
  }
  .masthead .caps {
    color: var(--accent);
    margin-bottom: 4px;
    font-family: var(--sans);
    font-size: 9.5px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .masthead .caps .dot {
    color: var(--ink-30);
  }
  .masthead .title {
    margin: 0;
    font-family: var(--serif);
    font-size: 22px;
    font-weight: 400;
    color: var(--ink);
    line-height: 1.1;
  }
  .masthead .italic {
    font-style: italic;
  }

  .section-head {
    flex: 0 0 auto;
    padding: 12px 22px 6px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  .papers-head {
    border-top: 1px solid var(--ink-12);
    padding-top: 12px;
  }
  .caps {
    font-family: var(--sans);
    font-size: 9.5px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--accent);
  }
  .hint {
    font-family: var(--mono);
    font-size: 9.5px;
    letter-spacing: 0.4px;
    text-transform: uppercase;
    color: var(--ink-30);
  }
  .add-btn {
    font-family: var(--sans);
    font-size: 9.5px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    padding: 3px 10px;
    border: 1px solid var(--ink);
    background: transparent;
    color: var(--ink);
    cursor: pointer;
  }
  .add-btn:hover { background: var(--ink); color: var(--panel); }

  .new-row {
    flex: 0 0 auto;
    padding: 6px 22px 10px;
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
    padding: 3px 8px;
    font-family: var(--sans);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    border: 1px solid var(--ink);
    background: transparent;
    color: var(--ink);
    cursor: pointer;
  }
  .new-ok { background: var(--ink); color: var(--panel); }
  .new-cancel:hover { background: var(--ink); color: var(--panel); }

  .projects-scroll, .papers-scroll {
    overflow-y: auto;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  /* Projects pane: cap at ~40% of the rail so the papers list always
     has room to grow underneath even with many projects. */
  .projects-scroll {
    flex: 0 1 40%;
    padding-bottom: 6px;
  }
  /* Papers pane fills the remaining space. */
  .papers-scroll {
    flex: 1 1 auto;
    padding-bottom: 12px;
  }

  .proj-row {
    flex: 0 0 auto;
    width: 100%;
    text-align: left;
    background: transparent;
    color: var(--fg);
    border: 0;
    border-radius: 0;
    padding: 6px 22px;
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
    padding: 14px 22px;
    color: var(--ink-50);
    font-size: 12px;
    line-height: 1.5;
  }
  .empty p { margin: 0 0 4px; }

  .paper-row {
    flex: 0 0 auto;
    width: 100%;
    text-align: left;
    background: transparent;
    border: 0;
    padding: 8px 22px;
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
    font-size: 13px;
    line-height: 1.35;
    color: var(--ink);
  }
  .paper-row .sub {
    font-family: var(--mono);
    font-size: 10px;
    letter-spacing: 0.2px;
    color: var(--ink-50);
  }
</style>

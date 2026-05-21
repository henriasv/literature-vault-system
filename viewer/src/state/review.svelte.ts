/**
 * Review-mode state. Mirrors `libraryState` but lists projects (subdirs of
 * `ReviewNotes/`) and the papers inside the selected project.
 *
 * Project = directory name (slug) under `ReviewNotes/`. Each project is also
 * mirrored as a directory under `PDFs/reviewing/`. Review papers never appear
 * in the main library list — `list_papers` only walks `PaperNotes/`.
 */

import { invoke } from "@tauri-apps/api/core";
import type { PaperMeta } from "../lib/vault";

export interface ReviewProject {
  slug: string;
  paperCount: number;
}

/** Sort order for the papers list inside a selected project. Persists in
 *  localStorage so the user's pick survives reloads. */
export type ReviewSort = "added" | "name";
const SORT_KEY = "lv.reviewSort";

function loadInitialSort(): ReviewSort {
  if (typeof localStorage === "undefined") return "added";
  const v = localStorage.getItem(SORT_KEY);
  return v === "name" ? "name" : "added";
}

interface ReviewState {
  projects: ReviewProject[];
  selectedProject: string | null;
  papers: PaperMeta[];
  loading: boolean;
  sort: ReviewSort;
}

export const reviewState = $state<ReviewState>({
  projects: [],
  selectedProject: null,
  papers: [],
  loading: false,
  sort: loadInitialSort(),
});

export function setReviewSort(sort: ReviewSort): void {
  reviewState.sort = sort;
  if (typeof localStorage !== "undefined") {
    localStorage.setItem(SORT_KEY, sort);
  }
  sortPapersInPlace();
}

function sortPapersInPlace(): void {
  const list = [...reviewState.papers];
  if (reviewState.sort === "name") {
    list.sort((a, b) => (a.title || a.citekey).localeCompare(b.title || b.citekey));
  } else {
    list.sort((a, b) => b.added.localeCompare(a.added));
  }
  reviewState.papers = list;
}

export async function refreshReviewProjects(): Promise<void> {
  try {
    reviewState.projects = await invoke<ReviewProject[]>("list_review_projects");
    /* If the selected project was deleted on disk, drop the selection. */
    if (
      reviewState.selectedProject &&
      !reviewState.projects.some((p) => p.slug === reviewState.selectedProject)
    ) {
      reviewState.selectedProject = null;
      reviewState.papers = [];
    } else if (reviewState.selectedProject) {
      await refreshSelectedProjectPapers();
    }
  } catch (e) {
    console.error("list_review_projects failed", e);
  }
}

export async function selectReviewProject(slug: string | null): Promise<void> {
  reviewState.selectedProject = slug;
  await refreshSelectedProjectPapers();
}

async function refreshSelectedProjectPapers(): Promise<void> {
  if (!reviewState.selectedProject) {
    reviewState.papers = [];
    return;
  }
  reviewState.loading = true;
  try {
    reviewState.papers = await invoke<PaperMeta[]>("list_review_papers", {
      project: reviewState.selectedProject,
    });
    sortPapersInPlace();
  } catch (e) {
    console.error("list_review_papers failed", e);
    reviewState.papers = [];
  } finally {
    reviewState.loading = false;
  }
}

export async function toggleReviewDone(citekey: string, done: boolean): Promise<void> {
  await invoke("set_review_done", { citekey, done });
  /* Optimistic patch so the row updates instantly; the watcher will
   * follow up with a refresh that confirms (and corrects, if writing
   * failed). */
  const idx = reviewState.papers.findIndex((p) => p.citekey === citekey);
  if (idx >= 0) {
    reviewState.papers[idx] = { ...reviewState.papers[idx], done };
  }
}

export async function createReviewProjectFlow(slug: string): Promise<string> {
  const created = await invoke<string>("create_review_project", { slug });
  await refreshReviewProjects();
  return created;
}

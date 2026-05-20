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

interface ReviewState {
  projects: ReviewProject[];
  selectedProject: string | null;
  papers: PaperMeta[];
  loading: boolean;
}

export const reviewState = $state<ReviewState>({
  projects: [],
  selectedProject: null,
  papers: [],
  loading: false,
});

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
  } catch (e) {
    console.error("list_review_papers failed", e);
    reviewState.papers = [];
  } finally {
    reviewState.loading = false;
  }
}

export async function createReviewProjectFlow(slug: string): Promise<string> {
  const created = await invoke<string>("create_review_project", { slug });
  await refreshReviewProjects();
  return created;
}

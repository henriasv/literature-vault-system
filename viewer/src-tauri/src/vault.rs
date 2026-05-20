use std::path::{Path, PathBuf};

use anyhow::{anyhow, Context, Result};
use serde::{Deserialize, Serialize};

use crate::atomic::atomic_write;
use crate::frontmatter::{self, Frontmatter};

const DEFAULT_VAULT: &str = "~/literature-vault";

/// Resolve the active vault path. Preference order:
///   1. Persisted setting (chosen via File > Open Vault / File > New Vault).
///   2. `$LITERATURE_VAULT_ROOT` env var (scripts, CI, override).
///   3. The legacy hardcoded default — kept for backward compat; first-launch
///      installs that don't hit (1) or (2) will fall through here and the UI
///      should have already shown NoVault via [`is_vault_configured`].
pub fn vault_root() -> PathBuf {
    if let Some(p) = crate::settings::active_vault() {
        return p;
    }
    if let Ok(env) = std::env::var("LITERATURE_VAULT_ROOT") {
        return expand_tilde(&env);
    }
    expand_tilde(DEFAULT_VAULT)
}

/// True if a real vault is reachable. Used by the frontend to decide whether
/// to render the normal three-pane app or the NoVault welcome screen.
#[tauri::command]
pub fn is_vault_configured() -> bool {
    if crate::settings::active_vault().is_some() {
        return true;
    }
    if std::env::var("LITERATURE_VAULT_ROOT").is_ok() {
        return true;
    }
    // Last-chance fallback: the legacy default exists and looks like a vault.
    let p = expand_tilde(DEFAULT_VAULT);
    p.join("PaperNotes").is_dir()
}

/// Validate that `path` looks like an existing vault, then persist as active.
/// "Looks like a vault" = exists and has a `PaperNotes/` subdirectory.
/// Frontend reloads the window after this returns so all state picks up the
/// new root.
#[tauri::command]
pub fn pick_vault(path: String) -> Result<(), String> {
    let p = PathBuf::from(&path);
    if !p.is_dir() {
        return Err(format!("not a directory: {}", path));
    }
    if !p.join("PaperNotes").is_dir() {
        return Err(format!(
            "{} does not look like a vault — no PaperNotes/ subfolder",
            path
        ));
    }
    crate::settings::set_active_vault(p).map_err(|e| e.to_string())
}

/// Scaffold a fresh vault at `path` and persist it as the active vault.
///
/// Creates the canonical subfolders (`PaperNotes/`, `Bibfiles/`, `Inbox/`,
/// `Collections/`, `Projects/`). For `PDFs/`, either makes a plain directory
/// or symlinks to `pdfs_target` (useful when PDFs live in Google Drive /
/// Dropbox and shouldn't bloat the vault repo). Seeds an empty `index.json`
/// + a stub `library.bib` + a sensible `.gitignore`. Refuses to clobber an
/// existing `PaperNotes/`.
#[tauri::command]
pub fn create_vault(path: String, pdfs_target: Option<String>) -> Result<(), String> {
    let root = PathBuf::from(&path);
    if root.join("PaperNotes").is_dir() {
        return Err(format!(
            "{} already has a PaperNotes/ — refusing to overwrite",
            path
        ));
    }
    std::fs::create_dir_all(&root).map_err(|e| format!("mkdir {}: {}", path, e))?;
    for sub in &["PaperNotes", "Bibfiles", "Inbox", "Collections", "Projects"] {
        std::fs::create_dir_all(root.join(sub))
            .map_err(|e| format!("mkdir {}/{}: {}", path, sub, e))?;
    }

    // PDFs/ — symlink if a target was supplied, else a regular directory.
    // Guard against a recursive symlink: if the target is the vault itself or
    // a path inside it, refuse — that's how `PDFs/ -> <vault>` happens.
    let pdfs = root.join("PDFs");
    match pdfs_target.as_deref() {
        Some(t) if !t.is_empty() => {
            let target = PathBuf::from(t);
            let was_new = !target.exists();
            if was_new {
                std::fs::create_dir_all(&target)
                    .map_err(|e| format!("mkdir target {}: {}", t, e))?;
            }
            let canon_root = root
                .canonicalize()
                .map_err(|e| format!("canonicalize vault root: {}", e))?;
            let canon_target = target
                .canonicalize()
                .map_err(|e| format!("canonicalize PDFs target {}: {}", t, e))?;
            if canon_target == canon_root || canon_target.starts_with(&canon_root) {
                // Clean up the empty dir we just created, if any.
                if was_new {
                    let _ = std::fs::remove_dir(&target);
                }
                return Err(format!(
                    "PDFs target ({}) is inside the vault folder — pick a location outside it (e.g. Google Drive / Dropbox)",
                    t
                ));
            }
            #[cfg(unix)]
            std::os::unix::fs::symlink(&canon_target, &pdfs)
                .map_err(|e| format!("symlink PDFs/ -> {}: {}", t, e))?;
            #[cfg(not(unix))]
            std::fs::create_dir_all(&pdfs)
                .map_err(|e| format!("mkdir PDFs/: {}", e))?;
        }
        _ => {
            std::fs::create_dir_all(&pdfs).map_err(|e| format!("mkdir PDFs/: {}", e))?;
        }
    }

    // Seed files. Empty index, library.bib header, and a starter .gitignore so
    // users can `git init` cleanly. None of these clobber if they exist.
    let index = root.join("index.json");
    if !index.exists() {
        atomic_write(&index, b"{\n  \"by_hash\": {},\n  \"by_doi\": {},\n  \"by_arxiv\": {}\n}\n")
            .map_err(|e| format!("write index.json: {}", e))?;
    }
    let library_bib = root.join("library.bib");
    if !library_bib.exists() {
        atomic_write(
            &library_bib,
            b"% Auto-aggregated from Bibfiles/*.bib by the librarian scripts.\n\
              % Do not edit by hand -- your changes will be overwritten.\n",
        )
        .map_err(|e| format!("write library.bib: {}", e))?;
    }
    let gitignore = root.join(".gitignore");
    if !gitignore.exists() {
        atomic_write(
            &gitignore,
            b"# Big stuff that doesn't belong in git\n\
              PDFs/\n\
              Inbox/\n\
              embeddings.db\n\n\
              # Tooling caches\n\
              .bin/\n\
              .uv-cache/\n\
              .uv-pythons/\n\
              __pycache__/\n\n\
              # macOS\n\
              .DS_Store\n",
        )
        .map_err(|e| format!("write .gitignore: {}", e))?;
    }

    crate::settings::set_active_vault(root).map_err(|e| e.to_string())
}

fn expand_tilde(p: &str) -> PathBuf {
    if let Some(rest) = p.strip_prefix("~/") {
        if let Some(home) = dirs::home_dir() {
            return home.join(rest);
        }
    }
    PathBuf::from(p)
}

pub fn note_path(citekey: &str) -> PathBuf {
    vault_root().join("PaperNotes").join(format!("{citekey}.md"))
}
pub fn bib_path(citekey: &str) -> PathBuf {
    vault_root().join("Bibfiles").join(format!("{citekey}.bib"))
}
pub fn pdf_path(citekey: &str) -> PathBuf {
    vault_root().join("PDFs").join(format!("{citekey}.pdf"))
}
#[allow(dead_code)]
pub fn xfdf_path(citekey: &str) -> PathBuf {
    vault_root()
        .join("Annotations")
        .join(format!("{citekey}.xfdf"))
}
#[allow(dead_code)]
pub fn project_path(name: &str) -> PathBuf {
    vault_root().join("Projects").join(format!("{name}.md"))
}
pub fn inbox_dir() -> PathBuf {
    vault_root().join("Inbox")
}
pub fn index_json() -> PathBuf {
    vault_root().join("index.json")
}
pub fn embeddings_db() -> PathBuf {
    vault_root().join("embeddings.db")
}
pub fn paper_notes_dir() -> PathBuf {
    vault_root().join("PaperNotes")
}

// --- Review-mode paths -----------------------------------------------------
//
// Review papers live in their own subtrees so they never appear in the main
// library and never pollute library.bib. The synthetic citekey shape is
// `review:<project>:<stem>` — the `:` separators are illegal in filenames so
// they can't collide with library citekeys. All path-taking Tauri commands
// (`read_note`, `pdf_path_for`, `read_annotations`, …) check for the prefix
// via `parse_review_id` and route accordingly.

pub fn review_notes_dir() -> PathBuf {
    vault_root().join("ReviewNotes")
}
pub fn reviewing_pdfs_dir() -> PathBuf {
    vault_root().join("PDFs").join("reviewing")
}
pub fn review_note_path(project: &str, stem: &str) -> PathBuf {
    review_notes_dir().join(project).join(format!("{stem}.md"))
}
pub fn review_pdf_path(project: &str, stem: &str) -> PathBuf {
    reviewing_pdfs_dir().join(project).join(format!("{stem}.pdf"))
}
/// Annotation sidecars all live in one flat `Annotations/` directory. Review
/// papers get a sanitised name so the file lookup never touches the `review:`
/// citekey shape (which contains `:`, harmless in filenames but ugly).
pub fn review_annotation_path(project: &str, stem: &str) -> PathBuf {
    vault_root()
        .join("Annotations")
        .join(format!("review-{project}-{stem}.json"))
}

/// Split a review citekey `review:<project>:<stem>` into its parts. Returns
/// `None` for plain library citekeys.
pub fn parse_review_id(id: &str) -> Option<(String, String)> {
    let after = id.strip_prefix("review:")?;
    let (project, stem) = after.split_once(':')?;
    if project.is_empty() || stem.is_empty() {
        return None;
    }
    Some((project.to_string(), stem.to_string()))
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PaperMeta {
    pub citekey: String,
    pub title: String,
    pub authors: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub author_count: Option<u32>,
    pub year: i32,
    pub journal: Option<String>,
    pub doi: Option<String>,
    pub arxiv_id: Option<String>,
    pub added: String,
    pub tags: Vec<String>,
    #[serde(rename = "abstract")]
    pub abstract_: Option<String>,
    pub sha256_pdf: String,
    pub has_note: bool,
    pub has_pdf: bool,
}

impl PaperMeta {
    fn from_frontmatter(fm: Frontmatter, has_pdf: bool) -> Self {
        Self {
            citekey: fm.citekey,
            title: fm.title,
            authors: fm.authors,
            author_count: fm.author_count,
            year: fm.year,
            journal: fm.journal,
            doi: fm.doi,
            arxiv_id: fm.arxiv_id,
            added: fm.added,
            tags: fm.tags,
            abstract_: fm.abstract_,
            sha256_pdf: fm.sha256_pdf,
            has_note: true,
            has_pdf,
        }
    }
}

fn load_meta_from_path(path: &Path) -> Result<PaperMeta> {
    let contents = std::fs::read_to_string(path)
        .with_context(|| format!("read note {}", path.display()))?;
    let fm = frontmatter::parse(&contents)
        .with_context(|| format!("frontmatter in {}", path.display()))?;
    let has_pdf = pdf_path(&fm.citekey).is_file();
    Ok(PaperMeta::from_frontmatter(fm, has_pdf))
}

pub fn list_papers_impl() -> Result<Vec<PaperMeta>> {
    let dir = paper_notes_dir();
    if !dir.is_dir() {
        return Err(anyhow!("PaperNotes/ not found at {}", dir.display()));
    }
    let mut papers = Vec::new();
    let mut errors = 0usize;
    for entry in std::fs::read_dir(&dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.extension().and_then(|s| s.to_str()) != Some("md") {
            continue;
        }
        match load_meta_from_path(&path) {
            Ok(meta) => papers.push(meta),
            Err(e) => {
                errors += 1;
                eprintln!("[vault] skip {}: {:#}", path.display(), e);
            }
        }
    }
    if errors > 0 {
        eprintln!("[vault] loaded {} papers ({} skipped)", papers.len(), errors);
    }
    // Default sort: by `added` desc. The frontend may resort.
    papers.sort_by(|a, b| b.added.cmp(&a.added));
    Ok(papers)
}

pub fn paper_meta_impl(citekey: &str) -> Result<PaperMeta> {
    load_meta_from_path(&note_path(citekey))
}

pub fn read_note_impl(citekey: &str) -> Result<String> {
    let path = note_path(citekey);
    std::fs::read_to_string(&path).with_context(|| format!("read {}", path.display()))
}

pub fn write_note_impl(citekey: &str, contents: &str) -> Result<()> {
    // Refuse to write if frontmatter would be malformed — protects the vault from a viewer bug.
    frontmatter::validate_required(contents)
        .with_context(|| format!("frontmatter validation for {citekey}"))?;
    atomic_write(&note_path(citekey), contents.as_bytes())?;
    Ok(())
}

/// Update only the `tags:` block in the note's frontmatter, leaving the body and
/// every other frontmatter field byte-for-byte intact. Returns the new full file
/// contents so the caller can update its in-memory `lastSaved` baseline before
/// the notify watcher fires `note:changed` (otherwise the file-changed banner
/// would briefly appear after every tag edit).
pub fn set_tags_impl(citekey: &str, tags: &[String]) -> Result<String> {
    let path = note_path(citekey);
    let original = std::fs::read_to_string(&path)
        .with_context(|| format!("read {}", path.display()))?;
    let (yaml, body) = frontmatter::split(&original)?;
    let new_yaml = frontmatter::replace_tags_block(yaml, tags)?;
    let new_content = format!("---\n{new_yaml}---\n{body}");
    // Final sanity check: the rewritten file must still parse with all required fields.
    frontmatter::validate_required(&new_content)
        .with_context(|| format!("frontmatter validation for {citekey} after tag edit"))?;
    atomic_write(&path, new_content.as_bytes())?;
    Ok(new_content)
}

// -------- Tauri command shims --------

fn err_to_string<T>(r: Result<T>) -> Result<T, String> {
    r.map_err(|e| format!("{e:#}"))
}

#[tauri::command]
pub fn list_papers() -> Result<Vec<PaperMeta>, String> {
    err_to_string(list_papers_impl())
}

#[tauri::command]
pub fn paper_meta(citekey: String) -> Result<PaperMeta, String> {
    if let Some((project, stem)) = parse_review_id(&citekey) {
        let result: Result<PaperMeta> = (|| {
            let path = review_note_path(&project, &stem);
            let contents = std::fs::read_to_string(&path)
                .with_context(|| format!("read note {}", path.display()))?;
            let fm = frontmatter::parse(&contents)
                .with_context(|| format!("frontmatter in {}", path.display()))?;
            let has_pdf = review_pdf_path(&project, &stem).is_file();
            Ok(PaperMeta::from_frontmatter(fm, has_pdf))
        })();
        return err_to_string(result);
    }
    err_to_string(paper_meta_impl(&citekey))
}

#[tauri::command]
pub fn read_note(citekey: String) -> Result<String, String> {
    if let Some((project, stem)) = parse_review_id(&citekey) {
        let path = review_note_path(&project, &stem);
        return std::fs::read_to_string(&path)
            .map_err(|e| format!("read {}: {}", path.display(), e));
    }
    err_to_string(read_note_impl(&citekey))
}

#[tauri::command]
pub fn write_note(citekey: String, contents: String) -> Result<(), String> {
    if let Some((project, stem)) = parse_review_id(&citekey) {
        frontmatter::validate_required(&contents)
            .map_err(|e| format!("frontmatter validation for {citekey}: {e:#}"))?;
        let path = review_note_path(&project, &stem);
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|e| format!("mkdir {}: {}", parent.display(), e))?;
        }
        return atomic_write(&path, contents.as_bytes())
            .map_err(|e| format!("write {}: {}", path.display(), e));
    }
    err_to_string(write_note_impl(&citekey, &contents))
}

#[tauri::command]
pub fn set_tags(citekey: String, tags: Vec<String>) -> Result<String, String> {
    err_to_string(set_tags_impl(&citekey, &tags))
}

/// Concatenate the `Bibfiles/{citekey}.bib` for each given citekey, in the
/// order received. Missing bib files are emitted as a single `% missing` comment
/// so the caller still knows about the gap. Returns the joined bibtex string.
pub fn read_bibtex_impl(citekeys: &[String]) -> Result<String> {
    let mut out = String::new();
    for ck in citekeys {
        let path = bib_path(ck);
        match std::fs::read_to_string(&path) {
            Ok(contents) => {
                if !out.is_empty() && !out.ends_with("\n\n") {
                    if out.ends_with('\n') {
                        out.push('\n');
                    } else {
                        out.push_str("\n\n");
                    }
                }
                out.push_str(contents.trim_end());
                out.push('\n');
            }
            Err(_) => {
                if !out.is_empty() && !out.ends_with('\n') {
                    out.push('\n');
                }
                out.push_str(&format!("% missing bibfile for {ck}\n"));
            }
        }
    }
    Ok(out)
}

#[tauri::command]
pub fn read_bibtex(citekeys: Vec<String>) -> Result<String, String> {
    err_to_string(read_bibtex_impl(&citekeys))
}

#[tauri::command]
pub fn pdf_path_for(citekey: String) -> String {
    if let Some((project, stem)) = parse_review_id(&citekey) {
        return review_pdf_path(&project, &stem).to_string_lossy().into_owned();
    }
    pdf_path(&citekey).to_string_lossy().into_owned()
}

#[tauri::command]
pub fn vault_root_path() -> String {
    vault_root().to_string_lossy().into_owned()
}

/// Reassign an already-filed paper to a different CrossRef DOI. Shells out
/// to `scripts/reassign.py`, which owns the atomic rename + frontmatter
/// rewrite + index/library/Collections update transaction (with rollback).
/// Async because the script makes a network call to CrossRef.
#[tauri::command]
pub async fn reassign_with_doi(citekey: String, new_doi: String) -> Result<String, String> {
    let new_doi = new_doi.trim().to_string();
    if new_doi.is_empty() {
        return Err("new DOI is required".into());
    }
    let ck = citekey;
    let out = tokio::task::spawn_blocking(move || {
        crate::inbox::run_script(
            "reassign.py",
            &["--old-citekey", &ck, "--new-doi", &new_doi],
        )
        .map_err(|e| format!("{e:#}"))
    })
    .await
    .map_err(|e| format!("reassign_with_doi task: {e}"))??;
    Ok(out)
}

/// Read the per-paper annotation sidecar. Returns the raw JSON string —
/// the frontend round-trips it through EmbedPDF's `importAnnotations`. Empty
/// string when no sidecar exists yet (a paper that's never been annotated).
#[tauri::command]
pub fn read_annotations(citekey: String) -> Result<String, String> {
    let path = if let Some((project, stem)) = parse_review_id(&citekey) {
        review_annotation_path(&project, &stem)
    } else {
        vault_root().join("Annotations").join(format!("{citekey}.json"))
    };
    if !path.is_file() {
        return Ok(String::new());
    }
    std::fs::read_to_string(&path).map_err(|e| format!("read {}: {}", path.display(), e))
}

/// Write the per-paper annotation sidecar. Atomic via tempfile + rename.
/// Frontend calls this after every annotation change (debounced) with
/// `JSON.stringify(exportAnnotations())`. An empty body clears the sidecar
/// (deletes the file rather than writing `[]`) so paper folders stay clean.
#[tauri::command]
pub fn write_annotations(citekey: String, json: String) -> Result<(), String> {
    let dir = vault_root().join("Annotations");
    let path = if let Some((project, stem)) = parse_review_id(&citekey) {
        review_annotation_path(&project, &stem)
    } else {
        dir.join(format!("{citekey}.json"))
    };
    let trimmed = json.trim();
    // Clear sidecar entirely on empty (or "[]") — keeps the vault tidy.
    if trimmed.is_empty() || trimmed == "[]" {
        if path.exists() {
            std::fs::remove_file(&path)
                .map_err(|e| format!("rm {}: {}", path.display(), e))?;
        }
        return Ok(());
    }
    if !dir.is_dir() {
        std::fs::create_dir_all(&dir).map_err(|e| format!("mkdir {}: {}", dir.display(), e))?;
    }
    atomic_write(&path, json.as_bytes()).map_err(|e| format!("write {}: {}", path.display(), e))
}

/// Reassign with a user-supplied BibTeX entry instead of a DOI. The BibTeX
/// is written to a tempfile and passed to `reassign.py --new-bibtex-file`,
/// which extracts the new citekey from `@type{key, ...}` and runs the same
/// transaction.
#[tauri::command]
pub async fn reassign_with_bibtex(
    citekey: String,
    bibtex: String,
) -> Result<String, String> {
    let bibtex = bibtex.trim().to_string();
    if bibtex.is_empty() {
        return Err("BibTeX entry is required".into());
    }
    let ck = citekey;
    let out = tokio::task::spawn_blocking(move || -> Result<String, String> {
        let mut tmp = tempfile::Builder::new()
            .prefix("reassign-")
            .suffix(".bib")
            .tempfile()
            .map_err(|e| format!("tempfile: {e}"))?;
        use std::io::Write;
        tmp.write_all(bibtex.as_bytes())
            .map_err(|e| format!("write tempfile: {e}"))?;
        tmp.flush().ok();
        let tmp_path = tmp.path().to_string_lossy().to_string();
        let result = crate::inbox::run_script(
            "reassign.py",
            &["--old-citekey", &ck, "--new-bibtex-file", &tmp_path],
        )
        .map_err(|e| format!("{e:#}"));
        drop(tmp); // explicit drop = cleanup
        result
    })
    .await
    .map_err(|e| format!("reassign_with_bibtex task: {e}"))??;
    Ok(out)
}

// -------- Review-mode listing + project creation -----------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ReviewProject {
    pub slug: String,
    pub paper_count: u32,
}

#[tauri::command]
pub fn list_review_projects() -> Result<Vec<ReviewProject>, String> {
    let dir = review_notes_dir();
    if !dir.is_dir() {
        return Ok(Vec::new());
    }
    let mut out = Vec::new();
    for entry in std::fs::read_dir(&dir).map_err(|e| format!("read_dir {}: {e}", dir.display()))? {
        let entry = entry.map_err(|e| format!("entry: {e}"))?;
        let p = entry.path();
        if !p.is_dir() {
            continue;
        }
        let slug = match p.file_name().and_then(|n| n.to_str()) {
            Some(s) => s.to_string(),
            None => continue,
        };
        let mut count = 0u32;
        if let Ok(read) = std::fs::read_dir(&p) {
            for e2 in read.flatten() {
                if e2.path().extension().and_then(|s| s.to_str()) == Some("md") {
                    count += 1;
                }
            }
        }
        out.push(ReviewProject { slug, paper_count: count });
    }
    out.sort_by(|a, b| a.slug.cmp(&b.slug));
    Ok(out)
}

#[tauri::command]
pub fn list_review_papers(project: String) -> Result<Vec<PaperMeta>, String> {
    let dir = review_notes_dir().join(&project);
    if !dir.is_dir() {
        return Ok(Vec::new());
    }
    let mut papers = Vec::new();
    let mut errors = 0usize;
    for entry in std::fs::read_dir(&dir).map_err(|e| format!("read_dir {}: {e}", dir.display()))? {
        let entry = entry.map_err(|e| format!("entry: {e}"))?;
        let path = entry.path();
        if path.extension().and_then(|s| s.to_str()) != Some("md") {
            continue;
        }
        let stem = match path.file_stem().and_then(|s| s.to_str()) {
            Some(s) => s.to_string(),
            None => continue,
        };
        let loaded: Result<PaperMeta> = (|| {
            let contents = std::fs::read_to_string(&path)
                .with_context(|| format!("read note {}", path.display()))?;
            let fm = frontmatter::parse(&contents)
                .with_context(|| format!("frontmatter in {}", path.display()))?;
            let has_pdf = review_pdf_path(&project, &stem).is_file();
            Ok(PaperMeta::from_frontmatter(fm, has_pdf))
        })();
        match loaded {
            Ok(meta) => papers.push(meta),
            Err(e) => {
                errors += 1;
                eprintln!("[vault] skip review {}: {:#}", path.display(), e);
            }
        }
    }
    if errors > 0 {
        eprintln!("[vault] loaded {} review papers ({} skipped)", papers.len(), errors);
    }
    papers.sort_by(|a, b| b.added.cmp(&a.added));
    Ok(papers)
}

/// Validate a project slug is filesystem-safe. Reject path separators, NULs,
/// dotfiles, and obvious whitespace traps.
fn sanitize_project_slug(slug: &str) -> Result<String> {
    let trimmed = slug.trim();
    if trimmed.is_empty() {
        anyhow::bail!("project slug must not be empty");
    }
    if trimmed.contains('/') || trimmed.contains('\\') || trimmed.contains('\0') {
        anyhow::bail!("project slug must not contain path separators");
    }
    if trimmed.starts_with('.') {
        anyhow::bail!("project slug must not start with a dot");
    }
    Ok(trimmed.to_string())
}

/// Patch the title + authors fields in a freshly-dropped ReviewNote's
/// frontmatter. The drop pipeline writes minimal placeholders ("authors:
/// []", title derived from filename); this command is how the post-drop
/// metadata sheet commits user edits without forcing them to hand-edit
/// the markdown source. Preserves the note body verbatim and leaves the
/// other custom fields (review_project, bibtex_type, …) untouched.
#[tauri::command]
pub fn update_review_meta(
    citekey: String,
    title: String,
    authors: Vec<String>,
) -> Result<(), String> {
    let (project, stem) = parse_review_id(&citekey)
        .ok_or_else(|| format!("not a review citekey: {citekey}"))?;
    let path = review_note_path(&project, &stem);
    let original = std::fs::read_to_string(&path)
        .map_err(|e| format!("read {}: {e}", path.display()))?;
    let (yaml, body) = frontmatter::split(&original).map_err(|e| format!("{e:#}"))?;
    let new_yaml = patch_title_and_authors(yaml, title.trim(), &authors)
        .map_err(|e| format!("{e:#}"))?;
    let new_content = format!("---\n{new_yaml}---\n{body}");
    frontmatter::validate_required(&new_content)
        .map_err(|e| format!("frontmatter validation after edit: {e:#}"))?;
    atomic_write(&path, new_content.as_bytes())
        .map_err(|e| format!("write {}: {e}", path.display()))
}

/// Walk the YAML text line-by-line and replace the `title:` and
/// `authors:` blocks while leaving everything else byte-for-byte intact.
/// Mirrors `frontmatter::replace_tags_block`'s strategy so we don't
/// re-emit block scalars (abstract, bibtex) in unwanted ways.
fn patch_title_and_authors(yaml: &str, new_title: &str, new_authors: &[String]) -> Result<String> {
    let mut out = String::new();
    let mut lines = yaml.split_inclusive('\n').peekable();
    let mut title_done = false;
    let mut authors_done = false;
    while let Some(line) = lines.next() {
        let is_title = line.starts_with("title:") && !title_done;
        let is_authors = line.starts_with("authors:") && !authors_done;
        if is_title {
            out.push_str(&format!("title: {}\n", yaml_inline_string(new_title)));
            title_done = true;
            continue;
        }
        if is_authors {
            /* Drop the continuation lines (indented sequence items). */
            while let Some(peek) = lines.peek() {
                if peek.starts_with(' ') || peek.starts_with('\t') {
                    lines.next();
                } else {
                    break;
                }
            }
            if new_authors.is_empty() {
                out.push_str("authors: []\n");
            } else {
                out.push_str("authors:\n");
                for a in new_authors {
                    out.push_str(&format!("  - {}\n", yaml_inline_string(a)));
                }
            }
            authors_done = true;
            continue;
        }
        out.push_str(line);
    }
    if !title_done {
        anyhow::bail!("title: key not found in frontmatter");
    }
    if !authors_done {
        anyhow::bail!("authors: key not found in frontmatter");
    }
    Ok(out)
}

/// Quote a string for YAML inline use if it contains any indicator that
/// would otherwise confuse the parser. Empty string folds to `""` so
/// the field stays a string (not null).
fn yaml_inline_string(s: &str) -> String {
    if s.is_empty() {
        return "\"\"".into();
    }
    let needs_quote = s.contains(':')
        || s.contains('#')
        || s.contains('"')
        || s.starts_with(['"', '\'', '[', '{', '&', '*', '!', '|', '>', '-', '?', '@', '%']);
    if needs_quote {
        let escaped = s.replace('\\', "\\\\").replace('"', "\\\"");
        format!("\"{escaped}\"")
    } else {
        s.to_string()
    }
}

#[tauri::command]
pub fn create_review_project(slug: String) -> Result<String, String> {
    let safe = sanitize_project_slug(&slug).map_err(|e| format!("invalid slug: {e:#}"))?;
    std::fs::create_dir_all(review_notes_dir().join(&safe))
        .map_err(|e| format!("mkdir ReviewNotes/{}: {}", safe, e))?;
    std::fs::create_dir_all(reviewing_pdfs_dir().join(&safe))
        .map_err(|e| format!("mkdir PDFs/reviewing/{}: {}", safe, e))?;
    Ok(safe)
}

/// Same path as `vault_root_path` but with the user's home directory replaced
/// by `~` so the masthead can show a short, recognisable location instead of a
/// full absolute path. Falls back to the absolute path if the home dir can't
/// be determined or doesn't prefix the vault.
#[tauri::command]
pub fn vault_root_display() -> String {
    let root = vault_root();
    let s = root.to_string_lossy().into_owned();
    if let Some(home) = dirs::home_dir() {
        let home_s = home.to_string_lossy();
        if let Some(rest) = s.strip_prefix(home_s.as_ref()) {
            return format!("~{}", rest);
        }
    }
    s
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Run only when the real vault is mounted. Validates that every note's frontmatter
    /// parses with our parser — catches schema drift early.
    #[test]
    #[ignore]
    fn parses_every_real_note() {
        let dir = paper_notes_dir();
        if !dir.is_dir() {
            eprintln!("skipped: {} not a directory", dir.display());
            return;
        }
        let mut total = 0usize;
        let mut failed = Vec::new();
        for entry in std::fs::read_dir(&dir).unwrap() {
            let entry = entry.unwrap();
            let path = entry.path();
            if path.extension().and_then(|s| s.to_str()) != Some("md") {
                continue;
            }
            total += 1;
            if let Err(e) = load_meta_from_path(&path) {
                failed.push((path, format!("{e:#}")));
            }
        }
        if !failed.is_empty() {
            for (p, e) in &failed {
                eprintln!("FAIL {}: {}", p.display(), e);
            }
            panic!(
                "{}/{} notes failed to parse; rerun with `cargo test -- --ignored --nocapture`",
                failed.len(),
                total,
            );
        }
        println!("ok: parsed {total} notes");
    }
}

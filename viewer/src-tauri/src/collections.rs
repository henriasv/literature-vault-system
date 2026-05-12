//! User-curated paper groupings, per the vault DESIGN.md "Collections" section.
//!
//! Filesystem layout (under `{vault}/Collections/`):
//!
//!   <root>/<slug...>/index.md          ← required to count as a collection
//!   <root>/<slug...>/{child}/index.md  ← a sub-collection
//!
//! The slug is the relative path from `Collections/` (POSIX `/` separators).
//! Filename within each collection's directory is always `index.md`.
//!
//! Each `index.md` looks like:
//!
//! ```markdown
//! ---
//! name: thesis-3
//! slug: drafts/thesis-3
//! description: Confined water in clay layers
//! created: 2026-04-22T10:00:00+02:00
//! updated: 2026-05-07T14:33:21+02:00
//! ---
//!
//! # Free-form prose
//!
//! ## Papers
//!
//! - citekey1
//! - citekey2 — optional annotation after em-dash
//! ```
//!
//! Writers must replace ONLY the `## Papers` block (and the `updated:` field)
//! when changing membership; the rest of the file is preserved byte-for-byte.

use std::path::{Path, PathBuf};

use anyhow::{anyhow, bail, Context, Result};
use serde::{Deserialize, Serialize};

use crate::atomic::atomic_write;
use crate::frontmatter;
use crate::vault::vault_root;

const ROOT_DIR: &str = "Collections";
const INDEX_FILE: &str = "index.md";

/// One collection (corresponds to one directory under `Collections/`).
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Collection {
    /// Display name (human-readable; can have spaces).
    pub name: String,
    /// Relative path from `Collections/`, POSIX-style `/` separators, no
    /// leading or trailing slash. Empty string is reserved for the root.
    pub slug: String,
    pub description: Option<String>,
    pub created: Option<String>,
    pub updated: Option<String>,
    /// Citekeys in this collection's `## Papers` list, in document order.
    pub papers: Vec<String>,
    /// True if a subdirectory under this one ALSO contains an index.md
    /// (i.e. this collection has at least one sub-collection).
    pub has_children: bool,
}

fn collections_root() -> PathBuf {
    vault_root().join(ROOT_DIR)
}

/// Validate a slug: POSIX path of `[A-Za-z0-9_-]+` segments separated by `/`.
fn validate_slug(slug: &str) -> Result<()> {
    if slug.is_empty() {
        bail!("collection slug must not be empty");
    }
    if slug.starts_with('/') || slug.ends_with('/') || slug.contains("//") {
        bail!("malformed slug: {slug:?}");
    }
    for seg in slug.split('/') {
        if seg.is_empty() {
            bail!("malformed slug: {slug:?}");
        }
        if !seg
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
        {
            bail!("slug segment {seg:?} contains disallowed characters (only [A-Za-z0-9_-])");
        }
    }
    Ok(())
}

fn collection_dir(slug: &str) -> Result<PathBuf> {
    validate_slug(slug)?;
    Ok(collections_root().join(slug))
}

fn index_path(slug: &str) -> Result<PathBuf> {
    Ok(collection_dir(slug)?.join(INDEX_FILE))
}

/// Walk the `Collections/` tree, returning every (sub)collection that has
/// an `index.md`. Sorted lexicographically by slug so the tree renders
/// in a stable order.
pub fn list_collections_impl() -> Result<Vec<Collection>> {
    let root = collections_root();
    let mut out = Vec::new();
    if !root.is_dir() {
        return Ok(out);
    }
    walk(&root, &root, &mut out)?;
    out.sort_by(|a, b| a.slug.cmp(&b.slug));
    Ok(out)
}

fn walk(root: &Path, dir: &Path, out: &mut Vec<Collection>) -> Result<()> {
    let entries = match std::fs::read_dir(dir) {
        Ok(e) => e,
        Err(_) => return Ok(()),
    };
    for entry in entries {
        let entry = entry?;
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }
        let index = path.join(INDEX_FILE);
        if index.is_file() {
            // Compute slug = relative path from root, with POSIX separators.
            let rel = path.strip_prefix(root).unwrap_or(Path::new(""));
            let slug = rel
                .components()
                .map(|c| c.as_os_str().to_string_lossy().into_owned())
                .collect::<Vec<_>>()
                .join("/");
            // Validate; skip directories that don't conform.
            if validate_slug(&slug).is_err() {
                eprintln!("[collections] skip non-conforming slug at {}", path.display());
                continue;
            }
            match read_collection(&slug) {
                Ok(coll) => out.push(coll),
                Err(e) => eprintln!("[collections] skip {}: {e:#}", path.display()),
            }
        }
        // Recurse regardless of whether this dir has an index — children
        // are valid even if the parent isn't itself a collection.
        walk(root, &path, out)?;
    }
    // Pass 2: stamp `has_children` based on whether any other entry's slug
    // starts with this slug + "/". (Simpler to do here in caller after the
    // whole list is built.)
    Ok(())
}

/// Read a single collection's `index.md` and return its parsed form.
pub fn read_collection(slug: &str) -> Result<Collection> {
    let path = index_path(slug)?;
    let content = std::fs::read_to_string(&path)
        .with_context(|| format!("read {}", path.display()))?;
    let (yaml, body) = frontmatter::split(&content)?;
    let value: serde_yaml_ng::Value =
        serde_yaml_ng::from_str(yaml).context("collection frontmatter parse")?;
    let map = value
        .as_mapping()
        .ok_or_else(|| anyhow!("frontmatter is not a mapping in {}", path.display()))?;
    let get_string = |k: &str| -> Option<String> {
        map.get(serde_yaml_ng::Value::String(k.into()))
            .and_then(|v| v.as_str().map(|s| s.to_string()))
    };
    let name = get_string("name").unwrap_or_else(|| {
        slug.rsplit('/').next().unwrap_or(slug).to_string()
    });
    let description = get_string("description");
    let created = get_string("created");
    let updated = get_string("updated");
    let papers = parse_papers_section(body);
    let has_children = directory_has_child_index(&collection_dir(slug)?);
    Ok(Collection {
        name,
        slug: slug.to_string(),
        description,
        created,
        updated,
        papers,
        has_children,
    })
}

fn directory_has_child_index(dir: &Path) -> bool {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return false;
    };
    for entry in entries.flatten() {
        let p = entry.path();
        if p.is_dir() && p.join(INDEX_FILE).is_file() {
            return true;
        }
        if p.is_dir() {
            // Recurse one more level — a grandchild still counts as "has children"
            // for tree-rendering purposes.
            if directory_has_child_index(&p) {
                return true;
            }
        }
    }
    false
}

/// Extract the citekey bullets directly under a single `## Papers` heading.
/// Lines like `- {citekey}` or `- {citekey} — annotation`. Stops at the next
/// H2 (`## ...`) heading.
fn parse_papers_section(body: &str) -> Vec<String> {
    let mut in_papers = false;
    let mut out = Vec::new();
    for line in body.lines() {
        if line.starts_with("## ") {
            // A new H2 starts: are we entering Papers, or leaving it?
            let title = line.trim_start_matches('#').trim().to_lowercase();
            in_papers = title == "papers";
            continue;
        }
        if !in_papers {
            continue;
        }
        if let Some(rest) = line.strip_prefix("- ") {
            // `- {citekey}` or `- {citekey} — annotation`
            let citekey = rest
                .split_once(" —")
                .or_else(|| rest.split_once(" --"))
                .map(|(c, _)| c)
                .unwrap_or(rest)
                .trim()
                .to_string();
            if !citekey.is_empty() {
                out.push(citekey);
            }
        }
    }
    out
}

/// Replace the `## Papers` block (lines after the heading, up to the next
/// H2 or EOF) with a fresh bulleted list. Preserves everything else.
fn replace_papers_block(body: &str, papers: &[String]) -> String {
    let lines: Vec<&str> = body.lines().collect();
    let mut start: Option<usize> = None;
    let mut end: Option<usize> = None;
    for (i, line) in lines.iter().enumerate() {
        if start.is_none() {
            if line.starts_with("## ") {
                let title = line.trim_start_matches('#').trim().to_lowercase();
                if title == "papers" {
                    start = Some(i);
                }
            }
        } else if line.starts_with("## ") {
            end = Some(i);
            break;
        }
    }
    let mut out = String::new();
    let trailing_newline = body.ends_with('\n');
    if let Some(start) = start {
        // Up to and including the "## Papers" line.
        for line in &lines[..=start] {
            out.push_str(line);
            out.push('\n');
        }
        out.push('\n');
        for ck in papers {
            out.push_str("- ");
            out.push_str(ck);
            out.push('\n');
        }
        if !papers.is_empty() {
            out.push('\n');
        }
        if let Some(end) = end {
            for line in &lines[end..] {
                out.push_str(line);
                out.push('\n');
            }
        }
    } else {
        // No existing ## Papers — append one at the end.
        for line in &lines {
            out.push_str(line);
            out.push('\n');
        }
        if !body.ends_with("\n\n") {
            out.push('\n');
        }
        out.push_str("## Papers\n\n");
        for ck in papers {
            out.push_str("- ");
            out.push_str(ck);
            out.push('\n');
        }
    }
    if !trailing_newline && out.ends_with('\n') {
        out.pop();
    }
    out
}

/// Replace the `updated:` field in a YAML frontmatter block with the given
/// ISO timestamp. If the field doesn't exist yet, append it before the
/// closing fence (handled by the caller's reassembly).
fn replace_updated_in_yaml(yaml: &str, ts: &str) -> String {
    let mut found = false;
    let mut out = String::new();
    for line in yaml.lines() {
        if !found && line.starts_with("updated:") {
            out.push_str(&format!("updated: {ts}"));
            out.push('\n');
            found = true;
        } else {
            out.push_str(line);
            out.push('\n');
        }
    }
    if !found {
        out.push_str(&format!("updated: {ts}\n"));
    }
    out
}

fn now_iso() -> String {
    // Local time with offset, second precision.
    use std::time::{SystemTime, UNIX_EPOCH};
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    // We don't pull chrono in for one timestamp — just emit a UTC ISO. The
    // viewer's tz is informational; what matters is monotone ordering.
    let (year, month, day, hour, min, sec) = ymdhms_from_unix(secs);
    format!("{year:04}-{month:02}-{day:02}T{hour:02}:{min:02}:{sec:02}Z")
}

fn ymdhms_from_unix(mut secs: i64) -> (i32, u32, u32, u32, u32, u32) {
    let day_secs = 86400;
    let mut days = secs.div_euclid(day_secs);
    secs = secs.rem_euclid(day_secs);
    let hour = (secs / 3600) as u32;
    let min = ((secs % 3600) / 60) as u32;
    let sec = (secs % 60) as u32;
    // Civil from days-since-1970, via Howard Hinnant's algorithm.
    days += 719468; // shift epoch to 0000-03-01
    let era = days.div_euclid(146097);
    let doe = days.rem_euclid(146097) as u32;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = (yoe as i32) + (era as i32) * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = y + (if month <= 2 { 1 } else { 0 });
    (year, month, day, hour, min, sec)
}

/// Replace the membership of a collection. Reads, parses, mutates the
/// `## Papers` block and `updated:` field, atomic-writes.
fn write_papers(slug: &str, papers: &[String]) -> Result<Collection> {
    let path = index_path(slug)?;
    let content = std::fs::read_to_string(&path)
        .with_context(|| format!("read {}", path.display()))?;
    let (yaml, body) = frontmatter::split(&content)?;
    let new_yaml = replace_updated_in_yaml(yaml, &now_iso());
    let new_body = replace_papers_block(body, papers);
    let new_content = format!("---\n{new_yaml}---\n{new_body}");
    atomic_write(&path, new_content.as_bytes())?;
    read_collection(slug)
}

pub fn add_paper_impl(slug: &str, citekey: &str) -> Result<Collection> {
    let coll = read_collection(slug)?;
    if coll.papers.iter().any(|c| c == citekey) {
        return Ok(coll);
    }
    let mut next = coll.papers.clone();
    next.push(citekey.to_string());
    write_papers(slug, &next)
}

pub fn remove_paper_impl(slug: &str, citekey: &str) -> Result<Collection> {
    let coll = read_collection(slug)?;
    let next: Vec<String> = coll.papers.iter().filter(|c| *c != citekey).cloned().collect();
    if next.len() == coll.papers.len() {
        return Ok(coll);
    }
    write_papers(slug, &next)
}

pub fn create_collection_impl(
    slug: &str,
    name: Option<String>,
    description: Option<String>,
) -> Result<Collection> {
    validate_slug(slug)?;
    let dir = collection_dir(slug)?;
    let index = dir.join(INDEX_FILE);
    if index.is_file() {
        return Err(anyhow!("collection {slug} already exists"));
    }
    std::fs::create_dir_all(&dir)
        .with_context(|| format!("create_dir_all {}", dir.display()))?;
    let display_name = name.unwrap_or_else(|| {
        slug.rsplit('/').next().unwrap_or(slug).to_string()
    });
    let now = now_iso();
    let mut yaml = String::new();
    yaml.push_str(&format!("name: {}\n", yaml_escape(&display_name)));
    yaml.push_str(&format!("slug: {}\n", yaml_escape(slug)));
    if let Some(desc) = description {
        yaml.push_str(&format!("description: {}\n", yaml_escape(&desc)));
    }
    yaml.push_str(&format!("created: {now}\n"));
    yaml.push_str(&format!("updated: {now}\n"));
    let body = format!("# {display_name}\n\n## Papers\n\n");
    let content = format!("---\n{yaml}---\n{body}");
    atomic_write(&index, content.as_bytes())?;
    read_collection(slug)
}

fn yaml_escape(s: &str) -> String {
    if s.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-' || c == ' ' || c == '/') {
        s.to_string()
    } else {
        let escaped = s.replace('\\', "\\\\").replace('"', "\\\"");
        format!("\"{escaped}\"")
    }
}

pub fn delete_collection_impl(slug: &str) -> Result<()> {
    let dir = collection_dir(slug)?;
    let index = dir.join(INDEX_FILE);
    if index.is_file() {
        std::fs::remove_file(&index)
            .with_context(|| format!("remove {}", index.display()))?;
    }
    // Try to remove the directory if it's now empty (no children, no other files).
    let _ = std::fs::remove_dir(&dir);
    Ok(())
}

pub fn rename_collection_impl(old_slug: &str, new_slug: &str) -> Result<Collection> {
    let from = collection_dir(old_slug)?;
    let to = collection_dir(new_slug)?;
    if !from.is_dir() {
        bail!("collection {old_slug} not found");
    }
    if to.exists() {
        bail!("destination {new_slug} already exists");
    }
    if let Some(parent) = to.parent() {
        std::fs::create_dir_all(parent)
            .with_context(|| format!("create_dir_all {}", parent.display()))?;
    }
    std::fs::rename(&from, &to)
        .with_context(|| format!("rename {} → {}", from.display(), to.display()))?;
    // Update the slug + name in the moved index.md.
    let index = to.join(INDEX_FILE);
    if index.is_file() {
        let content = std::fs::read_to_string(&index)?;
        if let Ok((yaml, body)) = frontmatter::split(&content) {
            let new_yaml = update_slug_and_name_in_yaml(yaml, new_slug);
            let new_yaml = replace_updated_in_yaml(&new_yaml, &now_iso());
            let new_content = format!("---\n{new_yaml}---\n{body}");
            atomic_write(&index, new_content.as_bytes())?;
        }
    }
    read_collection(new_slug)
}

fn update_slug_and_name_in_yaml(yaml: &str, new_slug: &str) -> String {
    let leaf = new_slug.rsplit('/').next().unwrap_or(new_slug);
    let mut out = String::new();
    let mut saw_slug = false;
    let mut saw_name = false;
    for line in yaml.lines() {
        if line.starts_with("slug:") {
            out.push_str(&format!("slug: {}\n", yaml_escape(new_slug)));
            saw_slug = true;
        } else if line.starts_with("name:") && !saw_name {
            // Only rename if name appeared to be the old leaf; but easier to
            // just leave name alone (user may have customized it). Pass
            // through unchanged.
            out.push_str(line);
            out.push('\n');
            saw_name = true;
        } else {
            out.push_str(line);
            out.push('\n');
        }
    }
    if !saw_slug {
        out.push_str(&format!("slug: {}\n", yaml_escape(new_slug)));
    }
    if !saw_name {
        out.push_str(&format!("name: {}\n", yaml_escape(leaf)));
    }
    out
}

// ---- Tauri command shims ---------------------------------------------------

fn err_to_string<T>(r: Result<T>) -> Result<T, String> {
    r.map_err(|e| format!("{e:#}"))
}

#[tauri::command]
pub fn list_collections() -> Result<Vec<Collection>, String> {
    err_to_string(list_collections_impl())
}

#[tauri::command]
pub fn collection_add(slug: String, citekey: String) -> Result<Collection, String> {
    err_to_string(add_paper_impl(&slug, &citekey))
}

#[tauri::command]
pub fn collection_remove(slug: String, citekey: String) -> Result<Collection, String> {
    err_to_string(remove_paper_impl(&slug, &citekey))
}

#[tauri::command]
pub fn collection_create(
    slug: String,
    name: Option<String>,
    description: Option<String>,
) -> Result<Collection, String> {
    err_to_string(create_collection_impl(&slug, name, description))
}

#[tauri::command]
pub fn collection_delete(slug: String) -> Result<(), String> {
    err_to_string(delete_collection_impl(&slug))
}

#[tauri::command]
pub fn collection_rename(old_slug: String, new_slug: String) -> Result<Collection, String> {
    err_to_string(rename_collection_impl(&old_slug, &new_slug))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_papers_section() {
        let body = "# heading\n\n## Papers\n\n- a\n- b — note\n- c\n\n## Notes\n\n- not a citekey\n";
        let papers = parse_papers_section(body);
        assert_eq!(papers, vec!["a".to_string(), "b".to_string(), "c".to_string()]);
    }

    #[test]
    fn replace_papers_preserves_surroundings() {
        let body = "# heading\n\nprose here\n\n## Papers\n\n- old1\n- old2\n\n## Notes\n\nkeep me\n";
        let out = replace_papers_block(body, &["new".to_string()]);
        assert!(out.contains("# heading\n"));
        assert!(out.contains("prose here"));
        assert!(out.contains("- new\n"));
        assert!(!out.contains("- old1"));
        assert!(out.contains("## Notes\n"));
        assert!(out.contains("keep me"));
    }

    #[test]
    fn validate_slug_rejects_bad() {
        assert!(validate_slug("").is_err());
        assert!(validate_slug("/foo").is_err());
        assert!(validate_slug("foo/").is_err());
        assert!(validate_slug("foo//bar").is_err());
        assert!(validate_slug("foo/bar baz").is_err());
        assert!(validate_slug("foo/bar").is_ok());
        assert!(validate_slug("a-b_c/d-e").is_ok());
    }
}

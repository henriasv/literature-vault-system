use anyhow::{anyhow, bail, Context, Result};
use serde::{Deserialize, Serialize};
use serde_yaml_ng::Value;

const FENCE: &str = "---";

/// Split a note file into (yaml_text, body). Both are returned as borrowed slices.
/// Returns an error if the leading `---` fence or its closing counterpart is missing.
pub fn split<'a>(contents: &'a str) -> Result<(&'a str, &'a str)> {
    // Strip a UTF-8 BOM if some editor / OS write path inserted one — never present
    // in the agent-written notes, but we shouldn't refuse a valid file over it.
    let trimmed = contents.strip_prefix('\u{FEFF}').unwrap_or(contents);
    let after_open = trimmed
        .strip_prefix("---\n")
        .or_else(|| trimmed.strip_prefix("---\r\n"))
        .ok_or_else(|| {
            // Show the first ~24 bytes as hex so we can diagnose what's actually arriving
            // (BOM, NBSP, leading whitespace, alternate line separator, etc.).
            let preview = contents
                .as_bytes()
                .iter()
                .take(24)
                .map(|b| format!("{b:02x}"))
                .collect::<Vec<_>>()
                .join(" ");
            anyhow!(
                "note is missing leading `---` frontmatter fence (first 24 bytes: {preview})"
            )
        })?;
    let close_idx = find_close_fence(after_open)
        .ok_or_else(|| anyhow!("note is missing closing `---` frontmatter fence"))?;
    let yaml = &after_open[..close_idx];
    let after_close = &after_open[close_idx..];
    // Skip the closing fence itself plus its trailing newline (if any).
    let body_start = if let Some(rest) = after_close.strip_prefix("---\n") {
        after_open.len() - rest.len()
    } else if let Some(rest) = after_close.strip_prefix("---\r\n") {
        after_open.len() - rest.len()
    } else if after_close == "---" {
        after_open.len()
    } else {
        // find_close_fence already validated this, but guard anyway.
        bail!("malformed closing frontmatter fence");
    };
    Ok((yaml, &after_open[body_start..]))
}

fn find_close_fence(text: &str) -> Option<usize> {
    // Closing fence is `---` at the start of a line.
    let mut search_from = 0;
    while let Some(rel) = text[search_from..].find(FENCE) {
        let abs = search_from + rel;
        let at_line_start = abs == 0 || text.as_bytes()[abs - 1] == b'\n';
        let after = &text[abs + FENCE.len()..];
        let line_terminated =
            after.is_empty() || after.starts_with('\n') || after.starts_with("\r\n");
        if at_line_start && line_terminated {
            return Some(abs);
        }
        search_from = abs + FENCE.len();
    }
    None
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Frontmatter {
    pub citekey: String,
    pub title: String,
    pub authors: Vec<String>,
    #[serde(default)]
    pub author_count: Option<u32>,
    pub year: i32,
    #[serde(default)]
    pub journal: Option<String>,
    #[serde(default)]
    pub doi: Option<String>,
    #[serde(default)]
    pub arxiv_id: Option<String>,
    pub added: String,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default)]
    pub abstract_: Option<String>,
    pub sha256_pdf: String,
    /// Review-mode flag — present in ReviewNotes/<project>/<stem>.md only.
    /// Toggled via `set_review_done` to mark a student paper as graded.
    #[serde(default)]
    pub done: Option<bool>,
}

/// Parse and return strongly-typed frontmatter. The `abstract` key collides with the Rust
/// keyword, so we deserialize via a generic `Value` and pluck fields manually — this also
/// gives clearer error messages than `serde_yaml_ng`'s default.
pub fn parse(contents: &str) -> Result<Frontmatter> {
    let (yaml, _body) = split(contents)?;
    let value: Value =
        serde_yaml_ng::from_str(yaml).context("frontmatter YAML failed to parse")?;
    let map = value
        .as_mapping()
        .ok_or_else(|| anyhow!("frontmatter is not a YAML mapping"))?;

    let get_str = |k: &str| -> Option<String> {
        map.get(Value::String(k.into()))
            .and_then(|v| match v {
                Value::String(s) => Some(s.clone()),
                Value::Number(n) => Some(n.to_string()),
                _ => None,
            })
    };
    let get_opt_str = |k: &str| -> Option<Option<String>> {
        map.get(Value::String(k.into())).map(|v| match v {
            Value::Null => None,
            Value::String(s) => Some(s.clone()),
            Value::Number(n) => Some(n.to_string()),
            _ => None,
        })
    };
    let required_str = |k: &str| -> Result<String> {
        get_str(k).ok_or_else(|| anyhow!("frontmatter missing required string field `{k}`"))
    };

    let citekey = required_str("citekey")?;
    let title = required_str("title")?;
    let authors = match map.get(Value::String("authors".into())) {
        Some(Value::Sequence(seq)) => seq
            .iter()
            .filter_map(|v| match v {
                Value::String(s) => Some(s.clone()),
                _ => None,
            })
            .collect(),
        _ => bail!("frontmatter missing required sequence `authors`"),
    };
    let author_count = map
        .get(Value::String("author_count".into()))
        .and_then(|v| v.as_u64())
        .map(|n| n as u32);
    let year = map
        .get(Value::String("year".into()))
        .and_then(|v| v.as_i64())
        .ok_or_else(|| anyhow!("frontmatter missing required integer `year`"))?
        as i32;
    let journal = get_opt_str("journal").unwrap_or(None);
    let doi = get_opt_str("doi").unwrap_or(None);
    let arxiv_id = get_opt_str("arxiv_id").unwrap_or(None);
    let added = required_str("added")?;
    let tags = match map.get(Value::String("tags".into())) {
        Some(Value::Sequence(seq)) => seq
            .iter()
            .filter_map(|v| match v {
                Value::String(s) => Some(s.clone()),
                _ => None,
            })
            .collect(),
        Some(Value::Null) | None => Vec::new(),
        Some(_) => bail!("frontmatter `tags` is not a sequence"),
    };
    let abstract_ = get_opt_str("abstract").unwrap_or(None);
    let sha256_pdf = required_str("sha256_pdf")?;
    let done = map
        .get(Value::String("done".into()))
        .and_then(|v| v.as_bool());

    Ok(Frontmatter {
        citekey,
        title,
        authors,
        author_count,
        year,
        journal,
        doi,
        arxiv_id,
        added,
        tags,
        abstract_,
        sha256_pdf,
        done,
    })
}

/// Validate that contents start with frontmatter that contains every required field.
/// Used to gate writes so we never persist malformed YAML.
pub fn validate_required(contents: &str) -> Result<()> {
    let _ = parse(contents)?;
    Ok(())
}

/// Replace just the `tags:` block in the given YAML text, leaving everything else
/// byte-for-byte identical (no full serde round-trip — that would re-emit the
/// abstract block scalar in unwanted ways). Returns the new YAML text.
pub fn replace_tags_block(yaml: &str, new_tags: &[String]) -> Result<String> {
    let mut out = String::new();
    let mut lines = yaml.split_inclusive('\n').peekable();
    let mut found = false;
    while let Some(line) = lines.next() {
        let is_tags_line = if let Some(after) = line.strip_prefix("tags:") {
            let after = after.trim_end_matches(['\n', '\r']);
            after.is_empty() || after.starts_with(' ') || after.starts_with('[')
        } else {
            false
        };
        if is_tags_line && !found {
            // Skip the line itself + any indented continuation (sequence items).
            while let Some(peek) = lines.peek() {
                if peek.starts_with(' ') || peek.starts_with('\t') {
                    lines.next();
                } else {
                    break;
                }
            }
            if new_tags.is_empty() {
                out.push_str("tags: []\n");
            } else {
                out.push_str("tags:\n");
                for tag in new_tags {
                    out.push_str(&format_tag_item(tag));
                }
            }
            found = true;
        } else {
            out.push_str(line);
        }
    }
    if !found {
        bail!("tags: key not found in frontmatter");
    }
    Ok(out)
}

fn format_tag_item(tag: &str) -> String {
    if needs_yaml_quoting(tag) {
        let escaped = tag.replace('\\', "\\\\").replace('"', "\\\"");
        format!("  - \"{escaped}\"\n")
    } else {
        format!("  - {tag}\n")
    }
}

/// Conservative quoting: bare-string-safe characters are alnum, `_`, `-`, `:`.
/// Anything else (or an unsafe leading character) gets double-quoted.
fn needs_yaml_quoting(s: &str) -> bool {
    if s.is_empty() {
        return true;
    }
    let first = s.chars().next().unwrap();
    if !(first.is_ascii_alphanumeric() || first == '_') {
        return true;
    }
    !s.chars()
        .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-' || c == ':')
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_minimal_frontmatter() {
        let s = "---\ncitekey: a\ntitle: t\nauthors:\n  - x\nyear: 2025\nadded: 2025-01-01\ntags: []\nsha256_pdf: deadbeef\n---\nbody\n";
        let fm = parse(s).unwrap();
        assert_eq!(fm.citekey, "a");
        assert_eq!(fm.year, 2025);
        assert_eq!(fm.authors, vec!["x".to_string()]);
    }

    #[test]
    fn split_preserves_body() {
        let s = "---\ncitekey: a\ntitle: t\nauthors: [x]\nyear: 2025\nadded: 2025-01-01\ntags: []\nsha256_pdf: 0\n---\n# heading\nbody\n";
        let (_yaml, body) = split(s).unwrap();
        assert_eq!(body, "# heading\nbody\n");
    }

    #[test]
    fn rejects_missing_fence() {
        assert!(parse("citekey: a\n").is_err());
    }

    #[test]
    fn replaces_inline_empty_tags_with_block() {
        let yaml = "citekey: a\ntags: []\nsha256_pdf: x\n";
        let out = replace_tags_block(yaml, &["foo".to_string(), "cite:bar".to_string()]).unwrap();
        assert_eq!(
            out,
            "citekey: a\ntags:\n  - foo\n  - cite:bar\nsha256_pdf: x\n"
        );
    }

    #[test]
    fn replaces_block_tags_with_empty() {
        let yaml = "citekey: a\ntags:\n  - foo\n  - bar\nsha256_pdf: x\n";
        let out = replace_tags_block(yaml, &[]).unwrap();
        assert_eq!(out, "citekey: a\ntags: []\nsha256_pdf: x\n");
    }

    #[test]
    fn quotes_tags_with_special_chars() {
        let yaml = "citekey: a\ntags: []\nsha256_pdf: x\n";
        let out = replace_tags_block(yaml, &["has space".to_string()]).unwrap();
        assert_eq!(
            out,
            "citekey: a\ntags:\n  - \"has space\"\nsha256_pdf: x\n"
        );
    }

    #[test]
    fn preserves_abstract_block_scalar() {
        let yaml = "citekey: a\ntags: []\nabstract: |\n  line one\n  line two\nsha256_pdf: x\n";
        let out = replace_tags_block(yaml, &["foo".to_string()]).unwrap();
        // Abstract block scalar must not be rewritten.
        assert!(out.contains("abstract: |\n  line one\n  line two\n"));
        assert!(out.contains("tags:\n  - foo\n"));
    }
}

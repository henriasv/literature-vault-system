#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Search CrossRef for candidate DOIs by title/author/year.

Used when a PDF has no embedded DOI (extract_ids.py returned null/null).
The agent extracts title and author hints from the filename or
first-page text, calls this, and picks the best match before
proceeding to file_paper.py.

Usage:
    crossref_search.py --title "Strong strain dependence of friction"
    crossref_search.py --title "..." --author "Juel"
    crossref_search.py --title "..." --author "..." --year 2025
    crossref_search.py --query "kirigami friction graphene"

At least one of --title / --author / --query is required. Multiple are
combined (CrossRef AND-style relevance, not strict filter). --year is a
strict published-date filter.

Output: JSON list of candidates sorted by descending CrossRef score.
Each candidate: {doi, title, first_author, year, type, score}.
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.crossref.org/works"
UA = "literature-librarian/1.0 (research; mailto:noreply@example.com)"


def search(title: str | None = None, author: str | None = None,
           query: str | None = None, year: int | None = None,
           rows: int = 5) -> list[dict]:
    params: list[tuple[str, str]] = [("rows", str(rows))]
    if query:
        params.append(("query", query))
    if title:
        params.append(("query.title", title))
    if author:
        params.append(("query.author", author))
    if year is not None:
        params.append(("filter", f"from-pub-date:{year},until-pub-date:{year}"))

    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"CrossRef HTTP {e.code}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"CrossRef request failed: {e}", file=sys.stderr)
        return []

    items = data.get("message", {}).get("items", [])
    out: list[dict] = []
    for item in items:
        titles = item.get("title") or [""]
        authors = item.get("author", [])
        first_family = authors[0].get("family", "") if authors else ""
        first_given = authors[0].get("given", "") if authors else ""
        first_author = (
            f"{first_family}, {first_given}".rstrip(", ")
            if first_family or first_given
            else ""
        )
        year_val = None
        for f in ("published-print", "published-online", "issued", "published"):
            dp = item.get(f, {}).get("date-parts")
            if dp and dp[0]:
                year_val = dp[0][0]
                break
        out.append({
            "doi": item.get("DOI"),
            "title": titles[0],
            "first_author": first_author,
            "n_authors": len(authors),
            "year": year_val,
            "type": item.get("type"),
            "score": item.get("score"),
        })
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--title")
    p.add_argument("--author")
    p.add_argument("--query")
    p.add_argument("--year", type=int)
    p.add_argument("--top", type=int, default=5,
                   help="number of candidates to return (default: 5)")
    args = p.parse_args()

    if not (args.title or args.author or args.query):
        print("at least one of --title / --author / --query is required",
              file=sys.stderr)
        p.print_help(sys.stderr)
        return 2

    results = search(
        title=args.title, author=args.author, query=args.query,
        year=args.year, rows=args.top,
    )
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

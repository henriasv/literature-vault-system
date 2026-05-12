#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Resolve DOIs via CrossRef and output BibTeX with canonical citation keys.

Key format: {author}{year}-{journal}-{doi-suffix}  (see CITATION_KEYS.md for full spec)
Examples: stolte2024-jpcl-4c00605, musaelian2023-natcommun-s41467-023-36329-y

Usage:
    # Single DOI
    python doi2bib.py 10.1063/5.0180704

    # Multiple DOIs
    python doi2bib.py 10.1063/5.0180704 10.1021/acs.jctc.2c00512

    # From a file (one DOI per line)
    python doi2bib.py --file dois.txt

    # Check against existing bibliography for duplicates
    python doi2bib.py --bib library.bib 10.1063/5.0180704

    # Append verified entries directly to bibliography
    python doi2bib.py --bib library.bib --append 10.1063/5.0180704
"""

import argparse
import json
import os
import re
import sys
import textwrap
import unicodedata
import urllib.request
import urllib.error
from pathlib import Path

# CrossRef polite-pool contact. Set CROSSREF_MAILTO=you@example.com in the
# environment to opt into higher rate limits and let CrossRef / DataCite /
# OpenAlex reach you if the scripts misbehave. Unset = public pool, no
# mailto advertised.
_MAILTO = os.environ.get("CROSSREF_MAILTO", "").strip()
_UA = "doi2bib/1.0 (research" + (f"; mailto:{_MAILTO}" if _MAILTO else "") + ")"

# ── Journal abbreviation map ─────────────────────────────────────────────────
# CrossRef returns full journal names; we need short keys.
# This maps lowercase full names → abbreviation for the citation key.
# Add entries as needed.

JOURNAL_ABBREV = {
    "the journal of chemical physics": "jcp",
    "journal of chemical physics": "jcp",
    "j. chem. phys.": "jcp",
    "physical review letters": "prl",
    "phys. rev. lett.": "prl",
    "physical review b": "prb",
    "phys. rev. b": "prb",
    "physical review materials": "prmat",
    "phys. rev. mater.": "prmat",
    "journal of chemical theory and computation": "jctc",
    "j. chem. theory comput.": "jctc",
    "journal of the american chemical society": "jacs",
    "j. am. chem. soc.": "jacs",
    "the journal of physical chemistry letters": "jpcl",
    "journal of physical chemistry letters": "jpcl",
    "j. phys. chem. lett.": "jpcl",
    "the journal of physical chemistry a": "jpca",
    "journal of physical chemistry a": "jpca",
    "j. phys. chem. a": "jpca",
    "the journal of physical chemistry b": "jpcb",
    "journal of physical chemistry b": "jpcb",
    "j. phys. chem. b": "jpcb",
    "the journal of physical chemistry c": "jpcc",
    "journal of physical chemistry c": "jpcc",
    "j. phys. chem. c": "jpcc",
    "nature communications": "natcommun",
    "nat. commun.": "natcommun",
    "nature materials": "natmater",
    "nat. mater.": "natmater",
    "nature chemistry": "natchem",
    "nat. chem.": "natchem",
    "nature geoscience": "natgeosci",
    "nat. geosci.": "natgeosci",
    "nature physics": "natphys",
    "nat. phys.": "natphys",
    "nature methods": "natmethods",
    "nat. methods": "natmethods",
    "nature reviews materials": "natrevmater",
    "nat. rev. mater.": "natrevmater",
    "nature computational science": "natcomputsci",
    "nature": "nature",
    "science": "science",
    "science advances": "sciadv",
    "royal society open science": "rsos",
    "computer physics communications": "cpc",
    "comput. phys. commun.": "cpc",
    "new journal of physics": "njp",
    "new j. phys.": "njp",
    "journal of materials science": "jmatsci",
    "j. mater. sci.": "jmatsci",
    "theoretical chemistry accounts": "theochemacc",
    "theor. chem. acc.": "theochemacc",
    "nanoscale": "nanoscale",
    "chemical reviews": "chemrev",
    "chem. rev.": "chemrev",
    "angewandte chemie international edition": "angew",
    "angew. chem. int. ed.": "angew",
    "proceedings of the national academy of sciences": "pnas",
    "proc. natl. acad. sci. u.s.a.": "pnas",
    "chemical science": "chemsci",
    "chem. sci.": "chemsci",
    "npj computational materials": "npjcomputmater",
    "advanced materials": "advmater",
    "adv. mater.": "advmater",
    "molecular physics": "molphys",
    "mol. phys.": "molphys",
    "beilstein journal of nanotechnology": "beilstein",
    "beilstein j. nanotechnol.": "beilstein",
    "acs nano": "acsnano",
    "acs catalysis": "acscatal",
    "acs catal.": "acscatal",
    "journal of computational chemistry": "jcc",
    "j. comput. chem.": "jcc",
    "wiley interdisciplinary reviews: computational molecular science": "wires",
    "international journal of quantum chemistry": "ijqc",
    "int. j. quantum chem.": "ijqc",
    "electronic structure": "electrstruct",
    "machine learning: science and technology": "mlst",
    "mach. learn.: sci. technol.": "mlst",
    "digital discovery": "digdisc",
    # Earth & geo sciences
    "contributions to mineralogy and petrology": "ctma",
    "geochimica et cosmochimica acta": "geca",
    "journal of geophysical research: solid earth": "jogr",
    "journal of geophysical research": "jogr",
    "geophysical research letters": "grl",
    "earth and planetary science letters": "eaps",
    "earth-science reviews": "esr",
    "geology": "g",
    "geochemistry, geophysics, geosystems": "ggg",
    "mineralogy and petrology": "map",
    "minerals": "m",
    "geochemical perspectives": "gp",
    "geological society, london, special publications": "gsls",
    "reviews in mineralogy and geochemistry": "rima",
    "communications earth &amp; environment": "ceae",
    "communications earth & environment": "ceae",
    # Chemistry / materials
    "physical chemistry chemical physics": "pccp",
    "langmuir": "l",
    "crystal growth &amp; design": "cgad",
    "crystal growth & design": "cgad",
    "chemical physics letters": "cpl",
    "chemical physics": "cp",
    "advanced theory and simulations": "atas",
    "acta geotechnica": "ag",
    "cement and concrete research": "cacr",
    "journal of the american ceramic society": "jota",
    "energy procedia": "ep",
    "the journal of geology": "tjog",
    "journal of geology": "tjog",
    "chemical geology": "cg",
    "tectonophysics": "t",
    "teaching in higher education": "tihe",
    # Biology / biochemistry
    "trends in biochemical sciences": "tibs",
    "journal of molecular structure": "joms",
    "chemphyschem": "cppc",
    # Physics
    "physical review research": "prr",
    "physical review e": "pre",
    "applied physics letters": "apl",
    # Tribology / mechanics
    "tribology letters": "tl",
    # Environmental / chemistry
    "environmental toxicology and chemistry": "etac",
    # Materials
    "acs applied materials &amp; interfaces": "aami",
    "acs applied materials & interfaces": "aami",
    # Preprint servers — these register DOIs with CrossRef under their
    # own prefix (10.31234/, 10.26434/, 10.31223/, 10.1101/, …) so the
    # DOI → CrossRef → file_paper.py pipeline files them like any
    # peer-reviewed paper. CrossRef's `container-title` is the server
    # name itself; map each to a short abbrev so the citekey reads as
    # `{author}{year}-{server}-{doi-suffix}` (e.g. `smith2024-biorxiv-…`). */
    "psyarxiv": "psyarxiv",
    "psyarxiv preprints": "psyarxiv",
    "chemrxiv": "chemrxiv",
    "earthxiv": "eartharxiv",
    "eartharxiv": "eartharxiv",
    "engrxiv": "engrxiv",
    "biorxiv": "biorxiv",
    "medrxiv": "medrxiv",
    "ssrn electronic journal": "ssrn",
    "ssrn": "ssrn",
    "research square": "rsq",
    "authorea preprints": "authorea",
    "authorea": "authorea",
    "osf preprints": "osf",
    "osf": "osf",
    "socarxiv": "socarxiv",
    "techrxiv": "techrxiv",
    "preprints.org": "preprintsorg",
    "preprints": "preprintsorg",
    "egusphere": "egusphere",  # EGU preprints
    "esoar": "esoar",          # earth & space sciences open archive
    "lifexiv": "lifexiv",
    # arXiv itself only shows up here if a paper has a CrossRef-
    # registered DOI in addition to its arXiv ID — most don't, but
    # some journals (e.g. Quantum) cross-list. The arXiv-only path
    # in file_paper.py uses the dedicated `arxiv-…` suffix instead.
    "arxiv": "arxiv",
}

# Short display names for the journal field in the BibTeX entry
JOURNAL_DISPLAY = {
    "the journal of chemical physics": "J. Chem. Phys.",
    "journal of chemical physics": "J. Chem. Phys.",
    "physical review letters": "Phys. Rev. Lett.",
    "physical review b": "Phys. Rev. B",
    "physical review materials": "Phys. Rev. Mater.",
    "journal of chemical theory and computation": "J. Chem. Theory Comput.",
    "journal of the american chemical society": "J. Am. Chem. Soc.",
    "the journal of physical chemistry letters": "J. Phys. Chem. Lett.",
    "journal of physical chemistry letters": "J. Phys. Chem. Lett.",
    "the journal of physical chemistry a": "J. Phys. Chem. A",
    "journal of physical chemistry a": "J. Phys. Chem. A",
    "the journal of physical chemistry b": "J. Phys. Chem. B",
    "journal of physical chemistry b": "J. Phys. Chem. B",
    "the journal of physical chemistry c": "J. Phys. Chem. C",
    "journal of physical chemistry c": "J. Phys. Chem. C",
    "nature communications": "Nat. Commun.",
    "nature materials": "Nat. Mater.",
    "nature chemistry": "Nat. Chem.",
    "nature geoscience": "Nat. Geosci.",
    "nature physics": "Nat. Phys.",
    "nature methods": "Nat. Methods",
    "nature reviews materials": "Nat. Rev. Mater.",
    "nature computational science": "Nat. Comput. Sci.",
    "nature": "Nature",
    "science": "Science",
    "science advances": "Sci. Adv.",
    "royal society open science": "R. Soc. Open Sci.",
    "computer physics communications": "Comput. Phys. Commun.",
    "new journal of physics": "New J. Phys.",
    "journal of materials science": "J. Mater. Sci.",
    "theoretical chemistry accounts": "Theor. Chem. Acc.",
    "nanoscale": "Nanoscale",
    "chemical reviews": "Chem. Rev.",
    "angewandte chemie international edition": "Angew. Chem. Int. Ed.",
    "proceedings of the national academy of sciences": "Proc. Natl. Acad. Sci. U.S.A.",
    "chemical science": "Chem. Sci.",
    "npj computational materials": "npj Comput. Mater.",
    "advanced materials": "Adv. Mater.",
    "molecular physics": "Mol. Phys.",
    "beilstein journal of nanotechnology": "Beilstein J. Nanotechnol.",
    "acs nano": "ACS Nano",
    "acs catalysis": "ACS Catal.",
    "journal of computational chemistry": "J. Comput. Chem.",
    "international journal of quantum chemistry": "Int. J. Quantum Chem.",
    "electronic structure": "Electron. Struct.",
    "machine learning: science and technology": "Mach. Learn.: Sci. Technol.",
    "digital discovery": "Digital Discovery",
    # Earth & geo sciences
    "contributions to mineralogy and petrology": "Contrib. Mineral. Petrol.",
    "geochimica et cosmochimica acta": "Geochim. Cosmochim. Acta",
    "journal of geophysical research: solid earth": "J. Geophys. Res. Solid Earth",
    "journal of geophysical research": "J. Geophys. Res.",
    "geophysical research letters": "Geophys. Res. Lett.",
    "earth and planetary science letters": "Earth Planet. Sci. Lett.",
    "earth-science reviews": "Earth-Sci. Rev.",
    "geology": "Geology",
    "geochemistry, geophysics, geosystems": "Geochem. Geophys. Geosyst.",
    "mineralogy and petrology": "Mineral. Petrol.",
    "minerals": "Minerals",
    "geochemical perspectives": "Geochem. Perspect.",
    "geological society, london, special publications": "Geol. Soc. London Spec. Publ.",
    "reviews in mineralogy and geochemistry": "Rev. Mineral. Geochem.",
    "communications earth &amp; environment": "Commun. Earth Environ.",
    "communications earth & environment": "Commun. Earth Environ.",
    # Chemistry / materials
    "physical chemistry chemical physics": "Phys. Chem. Chem. Phys.",
    "langmuir": "Langmuir",
    "crystal growth &amp; design": "Cryst. Growth Des.",
    "crystal growth & design": "Cryst. Growth Des.",
    "chemical physics letters": "Chem. Phys. Lett.",
    "chemical physics": "Chem. Phys.",
    "advanced theory and simulations": "Adv. Theory Simul.",
    "acta geotechnica": "Acta Geotech.",
    "cement and concrete research": "Cem. Concr. Res.",
    "journal of the american ceramic society": "J. Am. Ceram. Soc.",
    "energy procedia": "Energy Procedia",
    "the journal of geology": "J. Geol.",
    "journal of geology": "J. Geol.",
    "chemical geology": "Chem. Geol.",
    "tectonophysics": "Tectonophysics",
    "teaching in higher education": "Teach. High. Educ.",
    # Biology / biochemistry
    "trends in biochemical sciences": "Trends Biochem. Sci.",
    "journal of molecular structure": "J. Mol. Struct.",
    "chemphyschem": "ChemPhysChem",
    # Physics
    "physical review research": "Phys. Rev. Research",
    "physical review e": "Phys. Rev. E",
    "applied physics letters": "Appl. Phys. Lett.",
    # Tribology / mechanics
    "tribology letters": "Tribol. Lett.",
    # Environmental / chemistry
    "environmental toxicology and chemistry": "Environ. Toxicol. Chem.",
    # Materials
    "acs applied materials &amp; interfaces": "ACS Appl. Mater. Interfaces",
    "acs applied materials & interfaces": "ACS Appl. Mater. Interfaces",
}


def fetch_crossref(doi: str) -> dict:
    """Fetch metadata from CrossRef for a given DOI."""
    url = f"https://api.crossref.org/works/{doi}"
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data["message"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"  ERROR: DOI not found on CrossRef: {doi}", file=sys.stderr)
        else:
            print(f"  ERROR: CrossRef returned HTTP {e.code} for {doi}", file=sys.stderr)
        return {}
    except Exception as e:
        print(f"  ERROR: Failed to fetch {doi}: {e}", file=sys.stderr)
        return {}


def fetch_datacite(doi: str) -> dict:
    """Fetch metadata from DataCite and return it in the CrossRef-shaped
    `message` dict (so the rest of the pipeline doesn't have to branch).

    DataCite indexes many preprint servers CrossRef doesn't cover —
    PsyArXiv, EarthArxiv, SocArXiv, MetaArXiv, AfricArxiv (everything
    on OSF Preprints), plus most CalDigital archive holdings. The
    returned shape mirrors what `fetch_crossref` returns; missing
    fields default to sensible values so `make_canonical_key` /
    `make_bibtex` work without changes.
    """
    url = f"https://api.datacite.org/dois/{doi}"
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"  ERROR: DOI not found on DataCite: {doi}", file=sys.stderr)
        else:
            print(f"  ERROR: DataCite returned HTTP {e.code} for {doi}", file=sys.stderr)
        return {}
    except Exception as e:
        print(f"  ERROR: Failed to fetch DataCite {doi}: {e}", file=sys.stderr)
        return {}

    attrs = payload.get("data", {}).get("attributes", {})
    if not attrs:
        return {}

    # Title — pick the primary one. DataCite returns `titles: [{"title": "..."}]`.
    titles = attrs.get("titles") or []
    title = titles[0].get("title") if titles else ""

    # Authors — DataCite calls them `creators`. Each has `givenName` /
    # `familyName` OR a single `name` (often "Family, Given" or "Given Family").
    authors: list[dict] = []
    for c in attrs.get("creators", []):
        family = c.get("familyName") or ""
        given = c.get("givenName") or ""
        if not family and not given:
            name = (c.get("name") or "").strip()
            if "," in name:
                family, given = (s.strip() for s in name.split(",", 1))
            elif name:
                toks = name.split()
                family, given = toks[-1], " ".join(toks[:-1])
        if family or given:
            authors.append({"family": family, "given": given})

    # Year — DataCite has `publicationYear` as a string; fall back to
    # `dates[].date` filtering for `dateType == "Issued"` then to the
    # first valid date we can find.
    year_str: str | int = attrs.get("publicationYear") or ""
    if not year_str:
        for d in attrs.get("dates", []) or []:
            if d.get("dateType") in ("Issued", "Available", "Submitted"):
                year_str = (d.get("date") or "")[:4]
                if year_str:
                    break
    try:
        year_val: int = int(year_str)
    except (ValueError, TypeError):
        year_val = 0

    # "container-title" — what CrossRef would call the journal. DataCite
    # has `publisher` (the registering org, e.g. "Center for Open
    # Science") and `container.title` (the actual venue) — prefer the
    # latter, fall back to the former.
    container = (attrs.get("container") or {}).get("title")
    if not container:
        container = attrs.get("publisher") or ""

    # Build something shaped like CrossRef's "message" so downstream code
    # can read it unchanged.
    return {
        "DOI": attrs.get("doi") or doi,
        "title": [title] if title else [""],
        "author": authors,
        "container-title": [container] if container else [],
        "issued": {"date-parts": [[year_val]]} if year_val else {},
        "publisher": attrs.get("publisher") or "",
        "type": (attrs.get("types") or {}).get("resourceTypeGeneral", ""),
        "URL": attrs.get("url") or "",
        # DataCite descriptions can carry the abstract.
        "abstract": next(
            (d.get("description", "") for d in (attrs.get("descriptions") or [])
             if d.get("descriptionType") == "Abstract"),
            "",
        ),
    }


def fetch_metadata(doi: str) -> dict:
    """Resolve a DOI to CrossRef-shaped metadata. CrossRef first (covers
    peer-reviewed journals + most major preprint servers — bioRxiv,
    ChemRxiv, etc.); falls back to DataCite when CrossRef returns 404
    or an empty message (covers PsyArXiv, EarthArxiv, SocArXiv and
    other OSF-hosted preprints, plus various institutional repositories).

    Returns {} when both fail — caller decides what to do (typically
    surface "no metadata" and prompt the user for a manual BibTeX or
    a title-based CrossRef search)."""
    msg = fetch_crossref(doi)
    if msg:
        return msg
    print(f"  Falling back to DataCite for {doi}", file=sys.stderr)
    return fetch_datacite(doi)


def fetch_openalex_abstract(doi: str) -> str:
    """Fetch abstract from OpenAlex via inverted index reconstruction."""
    import urllib.parse
    url = f"https://api.openalex.org/works/https://doi.org/{urllib.parse.quote(doi)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        inv = data.get("abstract_inverted_index") or {}
        if not inv:
            return ""
        words: dict[int, str] = {}
        for word, positions in inv.items():
            for pos in positions:
                words[pos] = word
        return " ".join(words[i] for i in sorted(words))
    except Exception:
        return ""


def strip_accents_for_key(s: str) -> str:
    """Remove accents for citation key generation (ü→u, é→e, etc.)."""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def first_author_family(authors: list[dict]) -> str:
    """Extract first author's family name, lowercased, ASCII-only, alpha-only."""
    if not authors:
        return "unknown"
    family = authors[0].get("family", "")
    if not family:
        # Consortium/org — take first word of name
        name = authors[0].get("name", "unknown")
        family = name.split()[0] if name else "unknown"
    family = strip_accents_for_key(family).lower()
    # Keep only alpha characters (no digits, no hyphens)
    family = re.sub(r"[^a-z]", "", family)
    return family or "unknown"


def slugify_doi_suffix(doi: str) -> str:
    """Extract and slugify the DOI suffix (everything after first '/').

    See CITATION-KEYS.md for the full specification.
    """
    # Strip the registrant prefix (e.g., "10.1021/")
    idx = doi.find("/")
    if idx == -1:
        suffix = doi
    else:
        suffix = doi[idx + 1:]
    slug = suffix.lower()
    slug = re.sub(r"[^a-z0-9]", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug


def journal_abbrev(full_name: str) -> str:
    """Map full journal name to short abbreviation for citation key."""
    key = full_name.lower().strip()
    if key in JOURNAL_ABBREV:
        return JOURNAL_ABBREV[key]
    if key.startswith("the "):
        key2 = key[4:]
        if key2 in JOURNAL_ABBREV:
            return JOURNAL_ABBREV[key2]
    # Fallback: take initials of each word
    words = re.findall(r"[a-z]+", key)
    abbrev = "".join(w[0] for w in words[:4])
    print(f"  WARNING: Unknown journal '{full_name}', using abbreviation '{abbrev}'",
          file=sys.stderr)
    print(f"           Consider adding it to JOURNAL_ABBREV in doi2bib.py", file=sys.stderr)
    return abbrev


def make_canonical_key(doi: str, authors: list[dict], year, journal_full: str = "") -> str:
    """Compute the canonical citation key from DOI + metadata.

    Format: {author}{year}-{journal}-{doi_suffix}
    where doi_suffix is the slugified DOI suffix with any redundant journal
    prefix stripped (e.g. 'pnas-2501728122' → '2501728122' for PNAS).
    See CITATION_KEYS.md for the full specification.
    """
    author = first_author_family(authors)
    doi_slug = slugify_doi_suffix(doi)
    jabbrev = journal_abbrev(journal_full) if journal_full else ""
    if jabbrev:
        prefix = jabbrev + "-"
        doi_suffix = doi_slug[len(prefix):] if doi_slug.startswith(prefix) else doi_slug
        return f"{author}{year}-{jabbrev}-{doi_suffix}"
    return f"{author}{year}-{doi_slug}"


def journal_display(full_name: str) -> str:
    """Map full journal name to standard abbreviated display form."""
    key = full_name.lower().strip()
    if key in JOURNAL_DISPLAY:
        return JOURNAL_DISPLAY[key]
    if key.startswith("the "):
        key2 = key[4:]
        if key2 in JOURNAL_DISPLAY:
            return JOURNAL_DISPLAY[key2]
    return full_name


def strip_html(s: str) -> str:
    """Remove HTML tags from CrossRef titles (e.g., <i>GW</i> → GW).

    Inserts a space when a tag sits between two word characters to avoid
    producing run-together text like 'andGWwith'.
    """
    # Insert space where a tag bridges two word characters: "and<i>GW</i>with"
    s = re.sub(r"(?<=\w)<[^>]+>(?=\w)", " ", s)
    # Remove remaining tags (e.g., at start/end of string)
    s = re.sub(r"<[^>]+>", "", s)
    # Collapse any double spaces introduced
    s = re.sub(r"  +", " ", s)
    return s


def latex_escape(s: str) -> str:
    """Escape special characters for BibTeX values."""
    s = strip_html(s)
    # Protect & characters
    s = s.replace("&", r"\&")
    return s


def author_to_bibtex(author: dict) -> str:
    """Format a single author as 'Family, Given' for BibTeX."""
    family = author.get("family", "")
    given = author.get("given", "")
    if family and given:
        return f"{family}, {given}"
    return family or given


def make_bibtex(msg: dict, note: str = "") -> tuple[str, str]:
    """Convert CrossRef message to (citation_key, bibtex_string)."""
    authors = msg.get("author", [])
    title = msg.get("title", [""])[0]
    # Some titles have subtitle in a separate field
    subtitles = msg.get("subtitle", [])
    if subtitles and subtitles[0]:
        title = f"{title}: {subtitles[0]}"

    journal_full = ""
    if msg.get("container-title"):
        journal_full = msg["container-title"][0]

    volume = msg.get("volume", "")
    pages = msg.get("page", "")
    article_num = msg.get("article-number", "")
    doi = msg.get("DOI", "")
    year = None
    for date_field in ("published", "published-print", "published-online", "issued"):
        if msg.get(date_field, {}).get("date-parts"):
            year = msg[date_field]["date-parts"][0][0]
            if year:
                break
    if not year:
        year = "XXXX"

    # Build citation key (canonical format: author+year+doi-slug)
    if doi:
        citekey = make_canonical_key(doi, authors, year, journal_full)
    else:
        # Fallback for entries without DOI (should be rare)
        author_key = first_author_family(authors)
        journal_key = journal_abbrev(journal_full) if journal_full else "preprint"
        citekey = f"{author_key}-{journal_key}-{year}"
        print(f"  WARNING: No DOI — using legacy key format '{citekey}'", file=sys.stderr)

    # Format authors
    author_strs = [author_to_bibtex(a) for a in authors]
    author_field = " and ".join(author_strs)

    # Format pages: CrossRef uses "5297-5311", BibTeX convention is "5297--5311"
    if pages:
        pages = pages.replace("-", "--").replace("----", "--")
    elif article_num:
        pages = article_num

    journal_disp = journal_display(journal_full) if journal_full else ""

    # Build BibTeX
    lines = [f"@article{{{citekey},"]
    lines.append(f"  title   = {{{latex_escape(title)}}},")
    lines.append(f"  author  = {{{latex_escape(author_field)}}},")
    if journal_disp:
        lines.append(f"  journal = {{{journal_disp}}},")
    if volume:
        lines.append(f"  volume  = {{{volume}}},")
    if pages:
        lines.append(f"  pages   = {{{pages}}},")
    lines.append(f"  year    = {{{year}}},")
    if doi:
        lines.append(f"  doi     = {{{doi}}},")
    if note:
        lines.append(f"  note    = {{{note}}},")
    lines.append("}")

    return citekey, "\n".join(lines)


def load_existing_dois(bib_dir: str) -> dict[str, str]:
    """Scan {bib_dir}/*.bib and return {doi: citekey} mapping."""
    dois = {}
    bib_path = Path(bib_dir)
    if not bib_path.is_dir():
        return dois
    for f in bib_path.glob("*.bib"):
        current_key = None
        for line in f.read_text().splitlines():
            m = re.match(r"@\w+\{([^,]+),", line)
            if m:
                current_key = m.group(1).strip()
            m = re.match(r"\s*doi\s*=\s*\{([^}]+)\}", line, re.IGNORECASE)
            if m and current_key:
                dois[m.group(1).strip().lower()] = current_key
    return dois


def main():
    parser = argparse.ArgumentParser(
        description="Resolve DOIs via CrossRef and output BibTeX with canonical keys.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              %(prog)s 10.1063/5.0180704
              %(prog)s --save 10.1063/5.0180704 10.1021/acs.jctc.2c00512
              %(prog)s --file dois.txt --save
        """),
    )
    parser.add_argument("dois", nargs="*", help="DOI(s) to resolve")
    parser.add_argument("--file", "-f", help="File with one DOI per line")
    parser.add_argument("--bib-dir", default="Bibfiles",
                        help="Directory of per-entry .bib files (default: Bibfiles, vault layout)")
    parser.add_argument("--save", "-s", action="store_true",
                        help="Write each entry to {bib-dir}/{key}.bib")
    parser.add_argument("--note", "-n", default="",
                        help="Note to add to each entry (e.g., '[cited] RPA forces')")
    args = parser.parse_args()

    # Collect DOIs
    dois = list(args.dois)
    if args.file:
        with open(args.file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    dois.append(line)

    if not dois:
        parser.print_help()
        sys.exit(1)

    # Load existing DOIs for dedup
    existing_dois = load_existing_dois(args.bib_dir)
    if existing_dois:
        print(f"Loaded {len(existing_dois)} existing DOIs from {args.bib_dir}/", file=sys.stderr)

    entries = []
    for doi in dois:
        doi = doi.strip()
        # Strip URL prefix if present
        doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)

        print(f"\n--- {doi} ---", file=sys.stderr)

        # Check for duplicate
        if doi.lower() in existing_dois:
            existing_key = existing_dois[doi.lower()]
            print(f"  DUPLICATE: already in bibliography as '{existing_key}'", file=sys.stderr)
            continue

        msg = fetch_crossref(doi)
        if not msg:
            continue

        citekey, bibtex = make_bibtex(msg, note=args.note)
        print(f"  -> {citekey}", file=sys.stderr)

        entries.append((citekey, bibtex, doi))

    if not entries:
        print("\nNo new entries to output.", file=sys.stderr)
        sys.exit(0)

    # Output to stdout
    output = "\n\n".join(bib for _, bib, _ in entries)
    print()
    print(output)

    # Optionally save to individual bib files
    if args.save:
        bib_dir = Path(args.bib_dir)
        bib_dir.mkdir(parents=True, exist_ok=True)
        for citekey, bibtex, doi in entries:
            out_path = bib_dir / f"{citekey}.bib"
            out_path.write_text(bibtex + "\n")
            print(f"  Wrote {out_path}", file=sys.stderr)
        print(f"\nSaved {len(entries)} entries to {bib_dir}/", file=sys.stderr)


if __name__ == "__main__":
    main()

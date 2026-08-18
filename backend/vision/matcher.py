"""
Matches a VLM-read (title, author) guess against catalog.csv.

Design:
- Each catalog entry's title+alt_titles and author+author_alt_forms are
  flattened into unordered pools. No primary/alt priority — we take max
  similarity across all forms in the pool.
- Title and author are scored separately (rapidfuzz WRatio, handles
  substrings/reordering/typos), then combined into one confidence score.
- Confidence bands: >= AUTO_THRESHOLD -> auto-confirm, >= REVIEW_THRESHOLD
  -> human review, below -> no match / discard.
"""
import csv
from dataclasses import dataclass
from rapidfuzz import fuzz

AUTO_THRESHOLD = 90
REVIEW_THRESHOLD = 60

TITLE_WEIGHT = 0.65
AUTHOR_WEIGHT = 0.35


@dataclass
class CatalogEntry:
    id: int
    title: str
    author: str
    edition_note: str
    isbn: str
    title_pool: list
    author_pool: list


@dataclass
class MatchResult:
    entry: CatalogEntry
    score: float
    title_score: float
    author_score: float
    band: str  # "auto" | "review" | "none"


def _split_pool(primary: str, alts: str) -> list:
    pool = [primary.strip()] if primary and primary.strip() else []
    if alts:
        pool += [a.strip() for a in alts.split(";") if a.strip()]
    return pool


def load_catalog(path: str) -> list:
    entries = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            entries.append(CatalogEntry(
                id=int(row["id"]),
                title=row["title"],
                author=row["author"],
                edition_note=row.get("edition_note", ""),
                isbn=row.get("isbn", ""),
                title_pool=_split_pool(row["title"], row.get("alt_titles", "")),
                author_pool=_split_pool(row["author"], row.get("author_alt_forms", "")),
            ))
    return entries


def _max_sim(query: str, pool: list) -> float:
    if not query or not pool:
        return 0.0
    return max(fuzz.token_sort_ratio(query, form) for form in pool)


def score_entry(title_guess: str, author_guess: str, entry: CatalogEntry):
    t_score = _max_sim(title_guess, entry.title_pool)
    a_score = _max_sim(author_guess, entry.author_pool) if author_guess else t_score
    combined = t_score * TITLE_WEIGHT + a_score * AUTHOR_WEIGHT
    return combined, t_score, a_score


def match(title_guess: str, author_guess: str, catalog: list, top_n: int = 3) -> list:
    scored = []
    for entry in catalog:
        combined, t_score, a_score = score_entry(title_guess, author_guess, entry)
        if combined >= AUTO_THRESHOLD:
            band = "auto"
        elif combined >= REVIEW_THRESHOLD:
            band = "review"
        else:
            band = "none"
        scored.append(MatchResult(entry, combined, t_score, a_score, band))
    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:top_n]

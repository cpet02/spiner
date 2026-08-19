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
from rapidfuzz import fuzz, utils

AUTO_THRESHOLD = 90
REVIEW_THRESHOLD = 60

TITLE_WEIGHT = 0.65
AUTHOR_WEIGHT = 0.35

# If the top two candidates are within this many points of each other and
# no author was read to break the tie, the "auto" match is a coin flip
# between two real catalog entries (e.g. "Emma" -> Austen vs. McCall
# Smith), not a confident match -- demoted to "review" instead. Found
# live: with no author, every one of these ties scored a full 100.0 and
# auto-confirmed an arbitrary (lowest-id) entry.
TIE_MARGIN = 5.0


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
    # default_process lowercases + strips punctuation before comparing --
    # without it, an ALL-CAPS spine read (extremely common on real book
    # spines) scores catastrophically low against a mixed-case catalog
    # entry purely on character case, not actual title similarity. Found
    # live: "THE LORD OF THE RINGS" scored 28.6% against the catalog's
    # "The Lord of the Rings" -- an exact match, band "none".
    return max(
        fuzz.token_sort_ratio(query, form, processor=utils.default_process)
        for form in pool
    )


def score_entry(title_guess: str, author_guess: str, entry: CatalogEntry):
    t_score = _max_sim(title_guess, entry.title_pool)
    author_guess = (author_guess or "").strip()
    if author_guess:
        a_score = _max_sim(author_guess, entry.author_pool)
        combined = t_score * TITLE_WEIGHT + a_score * AUTHOR_WEIGHT
    else:
        # No author to score -- combined collapses to the title score
        # alone. Previously this reused t_score AS a_score too, which
        # made the 65/35 weighting a no-op and meant a missing author
        # cost nothing while a correct-but-abbreviated one (e.g.
        # "Martin" vs. "George R.R. Martin") could cost 15+ points and
        # get demoted to review. a_score is now honestly 0 -- it wasn't
        # scored, not scored-and-perfect.
        a_score = 0.0
        combined = t_score
    return combined, t_score, a_score


def _band_for(score: float) -> str:
    if score >= AUTO_THRESHOLD:
        return "auto"
    if score >= REVIEW_THRESHOLD:
        return "review"
    return "none"


def match(title_guess: str, author_guess: str, catalog: list, top_n: int = 3) -> list:
    # Round before banding, not after -- otherwise a combined score of
    # 89.96 bands "review" but displays as "90.0%" once pipeline.py
    # rounds it for the API response, which reads as a boundary bug to
    # anyone checking the number against the band.
    scored = [
        (entry, round(score, 1), t, a)
        for entry, (score, t, a) in (
            (entry, score_entry(title_guess, author_guess, entry)) for entry in catalog
        )
    ]
    scored.sort(key=lambda r: r[1], reverse=True)

    author_provided = bool((author_guess or "").strip())
    results = []
    for i, (entry, combined, t_score, a_score) in enumerate(scored[:top_n]):
        band = _band_for(combined)
        if band == "auto" and not author_provided and i == 0 and len(scored) > 1:
            runner_up = scored[1][1]
            if combined - runner_up < TIE_MARGIN:
                band = "review"
        results.append(MatchResult(entry, combined, t_score, a_score, band))
    return results

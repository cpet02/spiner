import os

from matcher import load_catalog, match

_CATALOG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "catalog.csv")
CATALOG = load_catalog(_CATALOG_PATH)


def top(title, author=""):
    return match(title, author, CATALOG, top_n=3)[0]


def test_duplicate_editions_need_author_or_note_to_disambiguate():
    # "1984" alone is ambiguous between id 1/2 (same title+author, diff
    # edition) -- matcher can't and shouldn't try to pick one; either is
    # a correct top match.
    r = top("1984", "George Orwell")
    assert r.entry.title == "1984"
    assert r.band == "auto"


def test_regional_title_variant():
    # Both UK/US rows list each other's title as alt_titles, so title text
    # alone can't disambiguate edition -- that's a genuine catalog trap.
    # We just confirm it resolves to *a* HP1 row with high confidence.
    r = top("Harry Potter and the Sorcerer's Stone", "J.K. Rowling")
    assert r.entry.id in (5, 6)
    assert r.band == "auto"


def test_homonym_title_disambiguated_by_author():
    r = top("Emma", "Alexander McCall Smith")
    assert r.entry.id == 9
    r2 = top("Emma", "Jane Austen")
    assert r2.entry.id == 8


def test_omnibus_vs_individual_volume():
    r = top("The Lord of the Rings", "J.R.R. Tolkien")
    assert r.entry.id == 12
    r2 = top("The Fellowship of the Ring", "J.R.R. Tolkien")
    assert r2.entry.id == 13


def test_substring_title_not_confused_with_series():
    r = top("A Game of Thrones", "George R.R. Martin")
    assert r.entry.id == 17  # not the box-set entry 16
    r2 = top("A Song of Ice and Fire", "George R.R. Martin")
    assert r2.entry.id == 16


def test_author_name_form_variants():
    # Last, First
    assert top("Crime and Punishment", "Dostoevsky, Fyodor").entry.id == 27
    # Initials
    assert top("Crime and Punishment", "F.M. Dostoevsky").entry.id == 27
    # First Last
    assert top("Crime and Punishment", "Fyodor Dostoevsky").entry.id == 27


def test_noisy_vlm_ocr_style_input():
    # simulate a slightly garbled spine read
    r = top("Fahrenheit 45l", "Ray Bradbury")  # OCR 1->l
    assert r.entry.id == 33
    assert r.band in ("auto", "review")


def test_no_match_falls_below_review():
    r = top("Some Book Not In Catalog At All", "Nobody Author")
    assert r.band == "none"


def test_title_only_no_author_still_resolves_unique_titles():
    r = top("The Alchemist")
    assert r.entry.id == 35
    assert r.band == "auto"


if __name__ == "__main__":
    import sys, traceback
    fns = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)

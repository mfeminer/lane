"""What a typed filter keeps, and what the screen says about it.

One implementation for all three list-shaped prompts, so this is where the matching
rule and the wording are pinned once. Each widget's own test file asserts that *it*
narrows, which is the part that could regress per screen.
"""

from __future__ import annotations

from lane.ui import filtering
from lane.ui.seam import Cell, Row


def test_a_filter_keeps_what_contains_it_whatever_the_case() -> None:
    """Substring rather than prefix, because a lane is remembered by a word in the
    middle of it as often as by how it starts."""
    texts = ["fix-broken-pagination", "Tidy up LOGS", "improve-lint"]

    assert filtering.matching(texts, "logs") == [1]
    assert filtering.matching(texts, "IN") == [0, 2]
    assert filtering.matching(texts, "") == [0, 1, 2], "no filter keeps everything"
    assert filtering.matching(texts, "zzz") == []


def test_a_row_is_matched_against_the_text_it_actually_draws() -> None:
    """The lead counts, because it is on screen. `Row`/`Cell` gain no second
    "searchable text" field: what the user can see is what they can filter on, and a
    field beside it is one more thing that can fall out of step with the cells."""
    row = Row(value="x", cells=(Cell("fix-pagination", lead="demo/"), Cell("✓ merged")))

    assert filtering.row_text(row) == "demo/fix-pagination ✓ merged"


def test_the_filter_says_what_it_is_and_how_much_it_left() -> None:
    """A filter is never a mode the user has to remember they are in: the text they
    typed is on screen, immediately under the title, with what it left of the list."""
    assert filtering.status(matched=2, total=9, text="fix") == "2 of 9 · filter: fix"


def test_the_filter_is_silent_when_nothing_is_typed() -> None:
    assert filtering.status(matched=9, total=9, text="") == ""


def test_no_matches_is_an_empty_state_rather_than_a_count_of_none() -> None:
    """docs/CONVENTIONS.md §12: one line, naming what to do about it — here the filter
    that is doing the hiding, since backspacing is what undoes it. `0 of 9` above a
    frozen, empty table is the shape §12 exists to forbid."""
    assert filtering.status(matched=0, total=9, text="zzz") == "No matches for 'zzz'."

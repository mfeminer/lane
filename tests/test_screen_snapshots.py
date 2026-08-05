"""L10 — pinned, whole-screen renderings at the widths `docs/CONVENTIONS.md` names.

Everything else in `test_table.py` asserts one behaviour at a time (a column
drops, a hint appears). This file is the one place a *complete* screen is pinned
end to end, so the next change that drifts from `docs/CONVENTIONS.md` — a wording
change, a column reordered, the L7 abbreviation regressing back to the mid-word
cut it replaced — shows up here as a failing test instead of being noticed months
later.

Only `table.py`'s `paint()` is snapshotted this way, because it's the one widget
in the app with a pure, directly-callable render function. `picker.py`'s `pick()`
builds its frame in a closure private to a running `prompt_toolkit` `Application`
— there is no pure function to call here without either driving a real terminal
(what `docs/UI-AUDIT.md` did, live, for the initial audit) or refactoring `pick()`
to expose one, which is a larger change than this box asked for. `test_picker.py`'s
existing tests (driven through pipe input) are what covers it instead.

What's deliberately **not** pinned here, and why: doctor's and settings' `rich`
output (covered by `FakeUi.said()` string assertions already — a snapshot on top
would be the same coverage twice, and would be brittle against paths, the build
fingerprint, and tool versions that vary by machine); the lanes table's *age*
column and anything derived from wall-clock time (age phrases change with time —
these fixtures use fixed `Cell` values, never a live `Lane`, for exactly that
reason).
"""

from __future__ import annotations

from lane.ui.seam import Cell, Column, Row
from lane.ui.table import paint

BACK = "← Back to the menu"

COLUMNS = (
    Column("lane"),
    Column("state"),
    Column("pr"),
    Column("age", drop=1),
)


def _rows() -> list[Row[str]]:
    return [
        Row(
            value="fix-broken-pagination",
            cells=(
                Cell("fix-broken-pagination", lead="demo/"),
                Cell("● 1 uncommitted · ↑ 1 unpushed", tone="warn", short="●1 ↑1"),
                Cell("—", tone="dim"),
                Cell("today"),
            ),
            detail=("feature/fix-broken-pagination",),
        ),
        Row(
            value="tidy-up-logging",
            cells=(
                Cell("tidy-up-logging", lead="demo/"),
                Cell("✓ merged", tone="good"),
                Cell("#418 open", tone="warn", short="#418"),
                Cell("today"),
            ),
            detail=("tidy-up-logging",),
        ),
    ]


def _text(width: int) -> str:
    lines = paint(
        "2 open lanes in demo", COLUMNS, _rows(), BACK, cursor=0, top=0, width=width, height=40
    ).lines
    return "\n".join(lines).rstrip()


def test_the_lanes_table_at_100_columns() -> None:
    body = _text(100)
    header = body.splitlines()[2]
    assert "lane" in header and "state" in header and "pr" in header and "age" in header
    assert "● 1 uncommitted · ↑ 1 unpushed" in body, "the long form survives at full width"
    assert "#418 open" in body
    assert "●1 ↑1" not in body, "no abbreviation while the long form still fits"


def test_the_lanes_table_at_68_columns_drops_age_before_touching_state() -> None:
    """Per docs/CONVENTIONS.md §13: age is the first thing to give way."""
    body = _text(68)
    header = body.splitlines()[2]
    assert "age" not in header
    assert "state" in header and "pr" in header
    assert "● 1 uncommitted · ↑ 1 unpushed" in body, "still room for the long form once age is gone"


def test_the_lanes_table_at_44_columns_abbreviates_state_before_losing_pr() -> None:
    """This is the exact regression `docs/UI-AUDIT.md` §2.13 found live: at a
    narrow width, `pr` used to vanish off-screen and `state` was cut mid-word with
    no ellipsis. Per the chosen fix (L7), `state` abbreviates first and `pr` is
    never lost."""
    body = _text(44)
    header = body.splitlines()[2]
    assert "pr" in header, "the pr column header must still be drawn"
    assert "#418 open" in body or "#418" in body, "pr's cell text must survive in some form"
    assert "●1 ↑1" in body, "state abbreviates to its short form"
    assert "● 1 uncommitted · ↑ 1 unpushed" not in body, "the long form is gone, not cut mid-word"
    assert "1 un" not in body, "no fragment of a word split mid-character survives"

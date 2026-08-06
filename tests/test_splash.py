"""The opening screen: a road with one task per lane, and the way out of it.

The splash is the one screen that is pure decoration, which is exactly why it is
pinned: it is drawn by hand from character arithmetic, so a change to the road
width, the stagger or the wordmark shows up here rather than on someone's
terminal. Whole-screen renderings at the promised widths live in
`test_screen_snapshots.py`; this file asserts one rule at a time.
"""

from __future__ import annotations

from lane.ui import splash
from lane.ui.splash import TAGLINE

WIDE = 80
TALL = 40


def _lines(width: int = WIDE, height: int = TALL, version: str = "0.0.2") -> list[str]:
    return splash.plain(splash.opening(width, height, version))


def test_the_road_is_bounded_top_and_bottom_by_the_same_bold_shoulder() -> None:
    """Both ends are the same weight: the splash is a stretch of road, not a banner."""
    lines = _lines()

    assert lines[0] == lines[-1]
    assert set(lines[0].strip()) == {"━"}


def test_each_word_of_the_tagline_travels_in_its_own_lane() -> None:
    """One task per lane is the product, so the words are not stacked in one line."""
    lines = _lines()

    carrying = [line for line in lines if any(word in line for word in ("one", "task", "per"))]
    assert len(carrying) == 3
    assert [line.strip().strip("│ ") for line in carrying] == ["one", "task", "per"]


def test_the_lanes_are_separated_by_dashed_markings() -> None:
    lines = _lines()

    assert sum(1 for line in lines if "╌" in line) == 3


def test_the_words_drift_further_right_lane_by_lane() -> None:
    """They are three tasks running side by side at different speeds, not a list."""
    lines = _lines()

    indents = [len(line) - len(line.lstrip()) for line in lines if "○" in line and "┗" not in line]
    assert indents == sorted(indents)
    assert len(set(indents)) == 3


def test_the_wordmark_is_centred_on_the_road() -> None:
    lines = _lines()

    road = next(line for line in lines if set(line.strip()) == {"━"})
    truck = [line for line in lines if "┏" in line or "┗" in line]
    assert len(truck) == 2
    left = len(truck[0]) - len(truck[0].lstrip())
    right = len(road.rstrip()) - len(truck[0].rstrip())
    assert abs(left - right) <= 1


def test_a_narrow_terminal_keeps_the_road_and_drops_the_car_bodies() -> None:
    """40–44 columns is the floor every screen here promises (docs/CONVENTIONS.md §13)."""
    lines = _lines(width=44)

    assert set(lines[0].strip()) == {"━"}
    assert not any("╭" in line for line in lines)
    assert [line.strip() for line in lines if line.strip() in TAGLINE] == list(TAGLINE)
    assert any("█" in line for line in lines)


def test_a_short_terminal_drops_the_car_bodies_so_the_menu_still_fits() -> None:
    """The splash is 19 lines boxed. A short window would push the menu off screen."""
    lines = _lines(height=24)

    assert not any("╭" in line for line in lines)
    assert len(lines) < 19


def test_below_a_road_width_there_is_just_the_version_line() -> None:
    lines = _lines(width=28)

    assert lines == ["lane 0.0.2"]


def test_the_farewell_falls_back_to_bare_words_on_a_narrow_terminal() -> None:
    assert splash.plain(splash.closing(28)) == [splash.FAREWELL]


def test_a_development_version_too_long_to_paint_gets_its_own_line() -> None:
    """Which copy is running is the one thing here that is not decoration."""
    lines = _lines(version="0.0.2.post1.dev4+g1a2b3c4")

    carrying = lines[-2]
    assert carrying.strip() == "v0.0.2.post1.dev4+g1a2b3c4"
    assert len(carrying.rstrip()) == len(lines[-1].rstrip())


def test_the_version_is_painted_bottom_right_inside_the_road() -> None:
    """Right where a road stencil would be: last line in, flush to the shoulder."""
    lines = _lines(version="1.2.3")

    carrying = [index for index, line in enumerate(lines) if "v1.2.3" in line]
    assert carrying == [len(lines) - 2]
    assert lines[carrying[0]].rstrip().endswith("v1.2.3")
    assert len(lines[carrying[0]].rstrip()) == len(lines[-1].rstrip())

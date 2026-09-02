"""The one corner hint every widget draws, and how it degrades.

The mechanism was `checklist.py`'s alone — three tiers, shrinking as the terminal
narrows. It is shared now, so this file is where the tiering and the placement are
pinned once rather than once per widget. Each widget's own test file still asserts
that *its* footer comes from here.
"""

from __future__ import annotations

from lane.ui.footer import Key, line, tiers


def test_the_hint_gives_up_the_arrows_first_then_what_each_key_does() -> None:
    """The order things can be spared in: nobody needs telling that arrows move, and
    the keys themselves are the part that has to survive."""
    assert tiers((Key("space", "answer"), Key("enter", "open"))) == (
        "↑↓ move · space answer · enter open",
        "space answer · enter open",
        "space · enter",
    )


def test_a_screen_with_no_keys_of_its_own_says_nothing() -> None:
    """`text` and `confirm` add no key and have nothing to choose between, so the one
    renderer answers them with silence — which is exactly what they draw today
    (docs/CONVENTIONS.md §2). An absence in two files becomes one rule."""
    assert tiers(()) == ("",)


def test_the_hint_is_drawn_in_the_bottom_right_corner() -> None:
    """Where a terminal already puts transient key hints — tmux's status line, fzf's
    own — and a margin on the right to match the two columns every screen indents by."""
    drawn = line((Key("enter", "choose"),), width=40)

    assert drawn.endswith("↑↓ move · enter choose")
    assert drawn.startswith("  "), "it is pushed across, not left-aligned"
    assert len(drawn) == 38


def test_the_scroll_position_rides_with_the_hint_and_is_given_up_before_it() -> None:
    """`1–19 of 40` is a convenience; what the keys do is the part a screen has to
    keep saying."""
    keys = (Key("enter", "choose"),)

    assert line(keys, width=60, shown=" · 1–19 of 40").endswith(
        "↑↓ move · enter choose · 1–19 of 40"
    )
    assert line(keys, width=30, shown=" · 1–19 of 40").endswith("↑↓ move · enter choose")


def test_the_corner_says_typing_filters_wherever_filtering_applies() -> None:
    """One more clause in the same tiered line — never a second hint line — and it is
    on all three list-shaped prompts, because filtering is on all three. `text` and
    `confirm` are not lists and say nothing, here as everywhere."""
    from lane.ui.checklist import keys_for
    from lane.ui.picker import KEYS, TEXT_KEYS

    assert [key.key for key in KEYS] == ["enter", "type"]
    assert [key.key for key in keys_for("open")] == ["space", "enter", "type"]
    assert [key.key for key in keys_for()] == ["space", "type"], "a leaf, where enter does nothing"
    assert TEXT_KEYS == ()

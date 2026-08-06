"""The opening screen, and the line that closes it.

A stretch of road: one task per lane, each word of the tagline travelling in a
lane of its own, the wordmark in the lane nearest you, and the version painted on
the asphalt in the bottom right. That is the product drawn rather than described —
three pieces of work side by side, none of them in each other's way.

Pure, like `table.py`'s `paint()`, and for the same reason: the layout is hand-made
character arithmetic, so it is only checkable if it can be called without a
terminal. `console_ui.py` turns these segments into `rich` output; nothing here
imports `rich`.

The road narrows before it disappears. `full` is the drawing above; `words` drops
the car bodies and lets the words ride the lanes bare; below that there is not
enough room for a road at all and the version line stands on its own.
"""

from __future__ import annotations

from dataclasses import dataclass

MARGIN = 2
"""The verge either side of the road, matching the two-space indent every other screen uses."""

MAX_ROAD = 60
MIN_ROAD = 30
"""Narrower than the wordmark's cab plus its verges — below this there is no road."""

FULL_ROAD = 46
MIN_HEIGHT = 16
FULL_HEIGHT = 30
"""The full drawing is 19 lines; below this the menu under it would be pushed off screen."""

TAGLINE = ("one", "task", "per")

WORDMARK = (
    "█     ▄▀▀▄  █▄  █  █▀▀▀",
    "█     █▄▄█  █ ▀▄█  █▀▀ ",
    "█▄▄▄  █  █  █   █  █▄▄▄",
)

FAREWELL = "see you in the next lane"

SHOULDER = "━"
MARKING = "╌"
WHEEL = "○"

# Styles are `rich`'s, resolved at the only place that prints them. `dim`/`bold`
# rather than a grey hex for the cars: the three of them fade up as they travel,
# and a fade built from theme-relative styles survives a light terminal, which a
# ramp of greys does not.
SHOULDER_STYLE = "bold"
MARKING_STYLE = "#d7af00"
BODY_STYLE = "#8a8a8a"
CAB_STYLE = "bold"
VERSION_STYLE = "#d7af00"
SPEEDS = ("dim", "", "bold")
"""One per lane: the word furthest along the road is the brightest."""

GRADIENT = ("#00d7ff", "#00afff", "#0087d7")
"""Down the wordmark's rows."""


@dataclass(frozen=True, slots=True)
class Segment:
    """A run of one style. A line is a tuple of them."""

    text: str
    style: str = ""


type Line = tuple[Segment, ...]


def plain(lines: list[Line]) -> list[str]:
    """The same lines with the styling dropped — what the tests and snapshots read."""
    return ["".join(segment.text for segment in line) for line in lines]


def opening(width: int, height: int, version: str) -> list[Line]:
    """The splash, drawn to fit the terminal it is going onto."""
    road = min(width - MARGIN * 2, MAX_ROAD)
    if road < MIN_ROAD or height < MIN_HEIGHT:
        return [(Segment(f"lane {version}", "bold"),)]

    boxed = road >= FULL_ROAD and height >= FULL_HEIGHT

    lines: list[Line] = [_shoulder(road)]
    for index, word in enumerate(TAGLINE):
        lines += _car(word, index, road, boxed=boxed)
        lines.append(_divider(road))
    lines += _truck(road, version)
    lines.append(_shoulder(road))
    return lines


def closing(width: int) -> list[Line]:
    """The way out: the road's last shoulder, with the goodbye set into it."""
    road = min(width - MARGIN * 2, MAX_ROAD)
    if road < MIN_ROAD:
        return [(Segment(FAREWELL, "dim"),)]

    inset = f" {FAREWELL} "
    left = (road - len(inset)) // 2
    right = road - len(inset) - left
    return [
        (
            Segment(" " * MARGIN + SHOULDER * left, SHOULDER_STYLE),
            Segment(inset),
            Segment(SHOULDER * right, SHOULDER_STYLE),
        )
    ]


def _shoulder(road: int) -> Line:
    return (Segment(" " * MARGIN + SHOULDER * road, SHOULDER_STYLE),)


def _divider(road: int) -> Line:
    marking = (MARKING + " ") * (road // 2)
    return (Segment(" " * MARGIN + marking.rstrip(), MARKING_STYLE),)


def _stagger(index: int, road: int, body: int) -> int:
    """Where this lane's traffic has got to.

    Spread across the road rather than fixed, so a wide terminal spaces the three
    of them out instead of leaving them clumped against the left verge.
    """
    room = max(0, road - body - MARGIN)
    return MARGIN + round(room * index / len(TAGLINE))


def _wheels(width: int, rail: str, left: int, right: int) -> str:
    body = [rail] * width
    body[left] = WHEEL
    body[right] = WHEEL
    return "".join(body)


def _car(word: str, index: int, road: int, *, boxed: bool) -> list[Line]:
    """One word of the tagline, in its lane. Boxed it is a car; bare it is just the word."""
    speed = SPEEDS[index]
    if not boxed:
        return [(Segment(" " * _stagger(index, road, len(word)) + word, speed),)]

    inner = f" {word} "
    body = len(inner) + 2
    indent = " " * _stagger(index, road, body)
    return [
        (Segment(f"{indent}╭{'─' * len(inner)}╮", BODY_STYLE),),
        (Segment(f"{indent}│", BODY_STYLE), Segment(inner, speed), Segment("│", BODY_STYLE)),
        (Segment(f"{indent}╰{_wheels(len(inner), '─', 1, len(inner) - 2)}╯", BODY_STYLE),),
    ]


def _truck(road: int, version: str) -> list[Line]:
    """The wordmark, centred, in the lane nearest the reader — and the version paint.

    The version rides the truck's own underside when it fits. A development build
    carries a version long enough that it would not, so it drops to a line of its
    own rather than being clipped: which copy is running is the one thing on this
    screen that is not decoration.
    """
    cab = max(len(row) for row in WORDMARK) + 2
    indent = " " * (MARGIN + (road - (cab + 2)) // 2)

    lines: list[Line] = [(Segment(f"{indent}┏{SHOULDER * cab}┓", CAB_STYLE),)]
    for row, colour in zip(WORDMARK, GRADIENT, strict=True):
        lines.append(
            (
                Segment(f"{indent}┃ ", CAB_STYLE),
                Segment(row.ljust(cab - 2), colour),
                Segment(" ┃", CAB_STYLE),
            )
        )
    underside = f"{indent}┗{_wheels(cab, SHOULDER, 3, cab - 4)}┛"
    lines.append((Segment(underside, CAB_STYLE),))

    paint = f"v{version}"
    room = MARGIN + road - len(paint)
    if room >= len(underside) + 2:
        lines[-1] = (
            Segment(underside, CAB_STYLE),
            Segment(" " * (room - len(underside))),
            Segment(paint, VERSION_STYLE),
        )
    else:
        lines.append((Segment(" " * room), Segment(paint, VERSION_STYLE)))
    return lines

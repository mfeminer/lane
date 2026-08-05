"""Rich rendering for the non-prompt output: the doctor report, the close summary.

Confined to the presentation layer along with `console_ui.py`, `picker.py` and
`table.py`. An action passes strings through the `Ui` seam and never touches rich.

The static table that used to live here is gone. The listing was its only caller,
and the listing is now a screen you stand in rather than something printed at you —
see ADR 0002. It drew itself with rich and then had a `prompt_toolkit` prompt
appended underneath, which is exactly the seam the redesign closed.
"""

from __future__ import annotations

from rich.console import Console
from rich.markup import escape as _escape


def make_console() -> Console:
    # `soft_wrap=False` keeps long paths from being silently truncated mid-word.
    return Console(highlight=False, soft_wrap=False)


def escape(text: str) -> str:
    """Stop a branch name containing brackets being read as rich markup."""
    return _escape(text)


def clip_long_words(text: str, width: int) -> str:
    """Only a single "word" (no internal space) wider than `width` degrades.

    A path has no spaces, so under `rich`'s default wrapping it's one long "word"
    that folds mid-character across lines once it doesn't fit — that's what a long
    path looked like before this existed. Ordinary prose is many short words and
    already wraps at the spaces between them, which must keep working, so this
    clips only the words that are themselves too long, one at a time, and leaves
    everything else untouched for `rich` to wrap normally.
    """
    if width <= 1:
        return text
    return " ".join(_clip_word(word, width) for word in text.split(" "))


def _clip_word(word: str, width: int) -> str:
    if len(word) <= width:
        return word
    return word[: width - 1] + "…"

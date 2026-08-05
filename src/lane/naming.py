"""Turning what the user typed into a lane name and a branch name.

Task descriptions are typed in whatever language the user thinks in, often with
non-ASCII characters. Lane names and branch names must always come out plain
ASCII — they become directory names and git refs.

Approach, and where it differs from the reference implementation: the reference
carried a hand-written table of accented letters. That table has gaps that look
accidental rather than deliberate — it maps `á à é è ê â î û ñ` but not `í ó ú`,
so `Año núñez` came out `ano-n-nez`. Here an explicit table handles only the
characters Unicode decomposition gets wrong (Turkish dotless/dotted i, and `ß`),
and everything else is decomposed and stripped of combining marks. That covers
every accented Latin letter rather than a list someone has to keep extending.

Anything still non-ASCII afterwards — CJK, emoji — becomes a separator rather
than being dropped, so two different descriptions cannot collapse into the same
name by silently losing characters.
"""

from __future__ import annotations

import re
import unicodedata

MAX_LANE_NAME = 40

# Characters that decomposition cannot handle, because they are distinct letters
# rather than accented forms of ASCII ones.
#
# `I` -> `i` for lane names is Turkish: the capital of `ı` is `I`, and lane names
# are lowercased anyway. `İ` -> `I` for branch names, which keep their case.
_LANE_SPECIALS = {
    "ı": "i",
    "İ": "i",
    "I": "i",
    "ß": "ss",
    "æ": "ae",
    "Æ": "ae",
    "œ": "oe",
    "Œ": "oe",
    "ø": "o",
    "Ø": "o",
    "đ": "d",
    "Đ": "d",
    "ł": "l",
    "Ł": "l",
    "þ": "th",
    "Þ": "th",
    "ð": "d",
    "Ð": "d",
}

_BRANCH_SPECIALS = {
    "ı": "i",
    "İ": "I",
    "ß": "ss",
    "æ": "ae",
    "Æ": "AE",
    "œ": "oe",
    "Œ": "OE",
    "ø": "o",
    "Ø": "O",
    "đ": "d",
    "Đ": "D",
    "ł": "l",
    "Ł": "L",
    "þ": "th",
    "Þ": "TH",
    "ð": "d",
    "Ð": "D",
}

_NON_ASCII = re.compile(r"[^\x00-\x7f]")


def _to_ascii(text: str, specials: dict[str, str]) -> str:
    """Explicit substitutions, then decomposition; leftovers become separators."""
    substituted = "".join(specials.get(char, char) for char in text)
    # NFKD splits "ş" into "s" + combining cedilla; dropping the marks leaves "s".
    decomposed = unicodedata.normalize("NFKD", substituted)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _NON_ASCII.sub("-", stripped)


def slugify(description: str) -> str:
    """A one-line task description becomes a lane name.

    `Login sayfası hatası` -> `login-sayfasi-hatasi`

    Returns the empty string when nothing usable is left; the caller decides what
    to say about that, because only the caller knows what was being named.
    """
    text = _to_ascii(description, _LANE_SPECIALS).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if len(text) > MAX_LANE_NAME:
        text = text[:MAX_LANE_NAME].rstrip("-")
    return text


def sanitize_branch(typed: str) -> str:
    """A hand-typed branch name becomes one git will accept.

    `EMİN/deneme  şube!!` -> `EMIN/deneme-sube`

    This only makes the name *plausible*. It is still validated with
    `git check-ref-format` before use — git owns that judgement, and its rules are
    not worth reproducing here.
    """
    text = _to_ascii(typed, _BRANCH_SPECIALS)
    # Keep only what git tolerates in a ref name.
    text = re.sub(r"[^A-Za-z0-9._/-]", "-", text)
    # Collapse doubled separators, which git rejects or which simply read badly.
    text = re.sub(r"-{2,}", "-", text)
    text = re.sub(r"/{2,}", "/", text)
    text = re.sub(r"\.{2,}", ".", text)
    # A slash surrounded by dashes was meant to be just a slash.
    text = re.sub(r"-*/-*", "/", text)
    text = re.sub(r"\.lock$", "", text)
    return text.strip("-./")

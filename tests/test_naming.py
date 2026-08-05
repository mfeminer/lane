"""Lane and branch names are always plain ASCII.

Task descriptions are typed in whatever language the user thinks in. Paths and
git refs must not be. Expectations come from `slugify` and `sanitize_branch` in
the reference implementation.
"""

from __future__ import annotations

import pytest

from lane.naming import MAX_LANE_NAME, sanitize_branch, slugify

# -- lane names ------------------------------------------------------------------


def test_the_headline_case_from_the_reference() -> None:
    assert slugify("Login sayfası hatası") == "login-sayfasi-hatasi"


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        # Turkish
        ("çğıöşü", "cgiosu"),
        ("ÇĞİÖŞÜ", "cgiosu"),
        ("Ağırlık hesaplama", "agirlik-hesaplama"),
        # dotted/dotless i: capital I becomes i, not left alone
        ("IIIı", "iiii"),
        # German
        ("Straße", "strasse"),
        ("Müller Bericht", "muller-bericht"),
        # Romance
        ("Café crème", "cafe-creme"),
        ("Año núñez", "ano-nunez"),
        ("í ó ú ä ë ï õ ã", "i-o-u-a-e-i-o-a"),  # gaps in the reference's table
        ("â î û é è ê á à", "a-i-u-e-e-e-a-a"),
    ],
)
def test_accented_letters_transliterate(description: str, expected: str) -> None:
    assert slugify(description) == expected


def test_unmapped_non_ascii_becomes_a_separator() -> None:
    """Anything outside the table is a separator, never smuggled through."""
    result = slugify("emoji 🚀 here")
    assert result == "emoji-here"
    assert result.isascii()


def test_cjk_yields_separators_only_and_so_is_unusable() -> None:
    assert slugify("日本語") == ""


def test_lowercased_and_separator_collapsed() -> None:
    assert slugify("Fix   THE    Export!!!") == "fix-the-export"


def test_leading_and_trailing_separators_are_trimmed() -> None:
    assert slugify("  --hello--  ") == "hello"


def test_capped_at_forty_characters_without_a_trailing_separator() -> None:
    name = slugify("a" * 60)
    assert len(name) == MAX_LANE_NAME == 40

    # A cap that lands on a separator must not leave one dangling.
    landing_on_separator = slugify("abcdefghij klmnopqrst uvwxyzabcd efghijkl mno")
    assert len(landing_on_separator) <= MAX_LANE_NAME
    assert not landing_on_separator.endswith("-")


def test_a_description_that_yields_nothing_gives_an_empty_name() -> None:
    """The caller reports this; slugify does not invent a name."""
    for useless in ("", "   ", "!!!", "---", "🚀"):
        assert slugify(useless) == ""


# -- branch names ----------------------------------------------------------------


def test_the_headline_branch_case_from_the_reference() -> None:
    assert sanitize_branch("EMİN/deneme  şube!!") == "EMIN/deneme-sube"


def test_branch_names_keep_their_case() -> None:
    """Unlike lane names: a branch is a name the user chose."""
    assert sanitize_branch("Feature/AddThing") == "Feature/AddThing"


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("feature/ok", "feature/ok"),
        ("has space", "has-space"),
        ("weird!!chars@@", "weird-chars"),
        # separator collapsing
        ("a--b", "a-b"),
        ("a//b", "a/b"),
        ("a..b", "a.b"),
        # -/- tidied to /
        ("a-/-b", "a/b"),
        ("feature-/thing", "feature/thing"),
        # .lock suffix is illegal in git
        ("branch.lock", "branch"),
        # trimmed of leading and trailing -, . and /
        ("/leading", "leading"),
        ("trailing/", "trailing"),
        ("-.-wrapped-.-", "wrapped"),
        ("...dots...", "dots"),
    ],
)
def test_branch_cleanup(typed: str, expected: str) -> None:
    assert sanitize_branch(typed) == expected


def test_branch_transliteration_preserves_case_of_accented_capitals() -> None:
    assert sanitize_branch("Çalışma") == "Calisma"
    assert sanitize_branch("ÖZEL") == "OZEL"
    assert sanitize_branch("Straße") == "Strasse"


def test_unusable_branch_input_yields_empty() -> None:
    for useless in ("", "   ", "///", "---", "🚀"):
        assert sanitize_branch(useless) == ""


def test_branch_output_is_always_ascii() -> None:
    for typed in ("Şube/İsim", "naïve/branch", "日本語/x"):
        assert sanitize_branch(typed).isascii()

"""L6: a `rich`-rendered word that overflows degrades like the lanes table does —
a single-line ellipsis, never `rich`'s default of folding mid-word across two.
"""

from __future__ import annotations

from rich.console import Console

from lane.ui.console_ui import ConsoleUi


def test_a_long_path_is_truncated_with_an_ellipsis_instead_of_wrapped() -> None:
    console = Console(width=20, record=True, highlight=False)
    ui = ConsoleUi(console=console)

    long_path = "/private/tmp/claude-501/some-long-scratchpad-directory/session/file.txt"
    ui.info(f"Running: {long_path}")

    lines = console.export_text().splitlines()
    non_blank = [line for line in lines if line.strip()]
    # The path is clipped as one whole word, so it may still wrap onto its own line
    # after "Running:" (ordinary word-wrap) — what must never happen is the word
    # itself being split mid-character across two lines, which is the original bug:
    # exactly one line carries (any part of) the path, and it ends in an ellipsis.
    path_lines = [line for line in non_blank if line.strip().startswith("/private")]
    assert len(path_lines) == 1
    assert path_lines[0].strip().endswith("…")


def test_ordinary_prose_still_wraps_at_its_spaces_instead_of_being_clipped() -> None:
    """The path fix above must not stop a long *sentence* from wrapping normally —
    only a single overlong word (a path) should ever be clipped."""
    console = Console(width=20, record=True, highlight=False)
    ui = ConsoleUi(console=console)

    prose = "Open a lane per task: its own worktree, branch and editor window."
    ui.detail(prose)

    lines = console.export_text().splitlines()
    non_blank = [line for line in lines if line.strip()]
    assert len(non_blank) > 1, "a long sentence should wrap across lines, not clip to one"
    assert not any(line.rstrip().endswith("…") for line in non_blank)
    assert " ".join(line.strip() for line in non_blank) == prose

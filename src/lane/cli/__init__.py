"""The entry point: a bare `lane` is the session, a subcommand is one thing done.

Two ways in, and the thing that stops them drifting is that the second one does not
*do* anything itself. `lane open` answers, in advance, the questions the interactive
`open` was going to ask, and then runs that same action (`cli.answers`). There is no
second implementation of what opening a lane means, and there must never be one.

Why there are subcommands at all, having been told there would never be: lane is now
driven by scripts and by agents as well as by a person twice a day, and neither can
move a cursor over a table or answer a prompt they cannot see. AGENTS.md carries the
reversal in full.

**The exit codes are a public interface.** They are the table in AGENTS.md, they are
what a script branches on, and an existing one is never renumbered.
"""

from __future__ import annotations

import sys

from lane import buildinfo
from lane.environment import Environment, RealEnvironment

EXIT_OK = 0
EXIT_REFUSED = 1
"""lane ran, and would not or could not do it."""

EXIT_USAGE = 2
"""The command line itself was wrong: unknown, contradictory or inapplicable flags."""

EXIT_NO_TTY = 3
"""An answer is needed and there is no terminal to ask in. Widened from its original
meaning — "lane is interactive and this is not a terminal" — and deliberately not
renumbered, because it is the same fact about the same situation."""

EXIT_NOT_FOUND = 4
"""A named project, lane or branch does not exist."""

EXIT_INTERRUPTED = 130
"""What a shell reports for a process killed by SIGINT."""


def _output_in_utf8() -> None:
    """Make lane's own output UTF-8, whatever the machine would otherwise have chosen.

    `lane doctor > report.txt` on Windows died with `UnicodeEncodeError: 'charmap'
    codec can't encode character '\u2713'` — the tick doctor puts in front of every
    healthy line. Python encodes a redirected stream with the **locale** encoding, and
    on Windows that is a code page that has no `✓`, no `◐` and none of the box glyphs
    the splash and the tables are drawn with. A console is fine, because Python writes
    to one through a wide-character API; a pipe or a file is not, and a pipe or a file
    is what a script gets.

    So lane states what its own output is rather than inheriting a guess. Not a Windows
    branch: a POSIX machine with a `C` locale has the same hole, and Python's own
    UTF-8-mode coercion for that case is a default somebody can turn off.

    `errors="replace"` is the backstop. A terminal that genuinely cannot carry a glyph
    should show a question mark; it should never end lane in a traceback — doctor of all
    things is the command that has to work on a machine where nothing else does.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            # A capture object, a pipe somebody wrapped, an embedding. None of them owe
            # lane a `reconfigure`, and refusing to start over it would be absurd.
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except OSError, ValueError:  # pragma: no cover - a stream that will not
            continue


def main(argv: list[str] | None = None, *, environment: Environment | None = None) -> int:
    _output_in_utf8()

    from lane.cli import parser as parsing

    parser = parsing.build()
    try:
        args = parser.parse_args(argv)
    except parsing.UsageError as exc:
        return _refuse(str(exc))

    # Answered before any prerequisite is consulted, so they work in CI and on a
    # machine where nothing lane needs is installed.
    if args.version:
        print(buildinfo.version_line())
        return EXIT_OK

    if args.help:
        # `lane close --help` is that subcommand's own help, and `lane config prefixes
        # --help` is that screen's — both argparse's rendering of the one definition
        # rather than prose kept beside it. The path comes from the parser that matched,
        # so nothing here knows how deep any particular command goes.
        path = getattr(args, "help_for", (args.command,) if args.command else ())
        printing = parsing.subparser(*path) if path else parser
        print(printing.format_help().rstrip())
        return EXIT_OK

    env = environment if environment is not None else RealEnvironment()

    if args.command is None:
        return _session(env)

    # Imported here, not at module scope, so --version and --help never pay for the
    # UI stack — the one path guaranteed to work without a terminal.
    from lane.cli import commands

    return commands.run(args, env)


def _session(env: Environment) -> int:
    """A bare `lane`: the interactive session, which still requires a terminal.

    Unchanged, and the reasoning is unchanged with it: there is no half-working
    non-interactive menu to maintain. What is new is that the advice at the end of
    the refusal is no longer "there is nothing else you can run".
    """
    if not env.is_interactive():
        print(
            f"{buildinfo.APP} is interactive and needs a terminal, "
            "but its input or output is not one.",
            file=sys.stderr,
        )
        print(
            f"Run '{buildinfo.APP}' directly in a terminal, or use a subcommand — "
            f"see '{buildinfo.APP} --help'.",
            file=sys.stderr,
        )
        return EXIT_NO_TTY

    from lane import app

    try:
        return app.run(env)
    except KeyboardInterrupt:
        # The session reports the interruptions it can see. This is the backstop for
        # the ones it cannot — one exit code, and never a traceback, which is the
        # only thing a user can do nothing with.
        return EXIT_INTERRUPTED


def _refuse(message: str) -> int:
    print(f"{buildinfo.APP}: {message}", file=sys.stderr)
    print(f"See '{buildinfo.APP} --help'.", file=sys.stderr)
    return EXIT_USAGE

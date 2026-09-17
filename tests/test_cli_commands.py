"""The five subcommands, end to end, against real temporary repositories.

Two things every one of them has to prove, and they are the whole design:

1. **Given every flag it needs, it behaves exactly as the interactive flow given the
   same answers** — same worktree, same branch, same metadata. There is one code
   path, and these are what would notice a second one appearing.
2. **Missing an answer, it is TTY-gated** — the real prompt where there is a
   terminal, a named refusal where there is not, and never a wait.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lane import cli
from lane.actions import ACTIONS, close_lane, enter_lane, list_lanes, open_lane
from lane.cli import commands
from lane.config import Config, ConfigStore
from lane.context import Context
from lane.git.cli_backend import CliGitBackend
from lane.lanes import LaneMeta, LaneStore
from lane.prepare import Step, Verb
from lane.prepare.store import PrepareStore
from lane.state import StateStore
from tests.conftest import build_repo, git
from tests.fakes import FakeEnvironment, FakeUi, StubGitHubClient


def test_doctor_as_a_subcommand_prints_the_same_report_without_a_terminal(
    xdg: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Doctor asks nothing, so nothing gates it: it is the smallest whole subcommand."""
    del xdg

    code = cli.main(["doctor"], environment=FakeEnvironment(interactive=False))

    out = capsys.readouterr().out
    assert code == cli.EXIT_OK
    assert "lane doctor" in out
    assert "git" in out


def test_doctor_as_json_puts_one_object_on_stdout_and_nothing_else_there(
    xdg: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`lane doctor --json | jq` has to work, which means stdout is JSON and only JSON."""
    del xdg

    code = cli.main(["doctor", "--json"], environment=FakeEnvironment(interactive=False))

    captured = capsys.readouterr()
    assert code == cli.EXIT_OK
    report = json.loads(captured.out)
    assert [check["name"] for check in report["checks"]][:3] == ["running", "git", "gh"]
    assert {check["status"] for check in report["checks"]} <= {"ok", "warn", "error"}


def test_the_json_report_carries_the_same_verdicts_the_printed_one_does(
    xdg: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One set of checks, two renderings — never two sets of checks."""
    del xdg
    nothing_installed = FakeEnvironment(interactive=False, tools={})

    cli.main(["doctor", "--json"], environment=nothing_installed)
    report = json.loads(capsys.readouterr().out)
    git = next(check for check in report["checks"] if check["name"] == "git")

    assert git["status"] == "error"
    assert git["facts"]["installed"] is False

    cli.main(["doctor"], environment=nothing_installed)
    printed = capsys.readouterr().out
    assert "git is not installed" in printed


# -- list --------------------------------------------------------------------------


def _configured(projects_root: Path, lanes_root: Path) -> None:
    """A real config file where `app.wire` will look for it, so these run the CLI
    end to end rather than a hand-built context that could differ from the real one."""
    ConfigStore().save(Config(projects_root=projects_root, lanes_root=lanes_root, editor="cursor"))


def _a_lane(projects_root: Path, lanes_root: Path, *, ignore: str = "") -> Path:
    _origin, clone = build_repo(projects_root / "_build")
    repo = projects_root / "demo"
    clone.rename(repo)

    if ignore:
        # Committed and pushed *before* the worktree exists, so the lane's own branch
        # carries it: only paths the lane's git ignores are ever brought in.
        (repo / ".gitignore").write_text(f"{ignore}\n")
        git(["add", ".gitignore"], cwd=repo)
        git(["commit", "--quiet", "-m", "ignore"], cwd=repo)
        git(["push", "--quiet", "origin", "HEAD"], cwd=repo)
        (repo / ignore.rstrip("/")).mkdir()
        (repo / ignore.rstrip("/") / "thing.txt").write_text("cached\n")

    lane = LaneStore(lanes_root).lane_path("demo", "pager")
    CliGitBackend().add_worktree_new_branch(repo, lane, "feature/pager", "origin/main")
    LaneStore(lanes_root).write_meta(
        "demo",
        "pager",
        LaneMeta(description="pager", base="main", repo=str(repo), start=""),
    )
    return repo


def test_list_prints_the_lanes_without_a_terminal(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Read-only, no prompts ever, and no screen to stand in: it prints and returns."""
    del xdg
    _a_lane(projects_root, lanes_root)
    _configured(projects_root, lanes_root)

    code = cli.main(["list"], environment=FakeEnvironment(interactive=False))

    out = capsys.readouterr().out
    assert code == cli.EXIT_OK
    assert "1 open lane in demo" in out
    assert "pager" in out


def test_list_as_json_is_one_array_carrying_what_the_table_shows(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del xdg
    _a_lane(projects_root, lanes_root)
    _configured(projects_root, lanes_root)

    code = cli.main(["list", "--json"], environment=FakeEnvironment(interactive=False))

    captured = capsys.readouterr()
    assert code == cli.EXIT_OK
    lanes = json.loads(captured.out)
    assert [lane["slug"] for lane in lanes] == ["demo/pager"]
    one = lanes[0]
    assert one["project"] == "demo"
    assert one["name"] == "pager"
    assert one["branch"] == "feature/pager"
    assert one["detached"] is False
    assert one["dirty"] == 0
    assert one["unpushed"] == 0
    # The pull request is structured, not the glyph the table draws: `—` tells a
    # reader "nothing to say here" and tells a script nothing at all.
    assert one["pull_request"] == {
        "state": "not-applicable",
        "number": None,
        "url": None,
        "detail": "origin is not a GitHub remote",
    }
    assert one["path"].endswith(str(Path("demo") / "pager"))


def test_list_with_no_lanes_is_an_empty_array_and_a_clean_exit(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing open is not a failure, and an empty list still parses."""
    del xdg
    _configured(projects_root, lanes_root)

    code = cli.main(["list", "--json"], environment=FakeEnvironment(interactive=False))

    assert code == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out) == []


# -- open --------------------------------------------------------------------------


def _repo(projects_root: Path, name: str = "demo") -> Path:
    _origin, clone = build_repo(projects_root / f"_build-{name}")
    repo = projects_root / name
    clone.rename(repo)
    return repo


def test_open_with_every_flag_creates_a_lane_and_does_not_launch_the_editor(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """A script or an agent has no use for a window appearing, so the editor is opt-in
    from the command line — and only from there: the session still launches it."""
    del xdg
    _repo(projects_root)
    _configured(projects_root, lanes_root)
    environment = FakeEnvironment(interactive=False, tools={"git": "/g", "cursor": "/c"})

    code = cli.main(
        [
            "open",
            "--project",
            "demo",
            "--description",
            "Fix the pager",
            "--branch-name",
            "bugfix/pager",
        ],
        environment=environment,
    )

    lane = lanes_root / "demo" / "fix-the-pager"
    assert code == cli.EXIT_OK
    assert (lane / ".git").exists()
    assert git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=lane).strip() == "bugfix/pager"
    assert environment.launched == []


def test_open_from_flags_and_open_from_the_menu_produce_the_same_lane(
    xdg: Path, tmp_path: Path, projects_root: Path, lanes_root: Path
) -> None:
    """The one test that would notice a second implementation appearing.

    Same answers, two routes in: one typed at a prompt, one given as flags. Worktree,
    branch and metadata have to come out identical, because it is the same code."""
    del xdg
    _repo(projects_root)
    _configured(projects_root, lanes_root)

    cli.main(
        ["open", "--project", "demo", "--description", "Fix the pager", "--branch-name", "x/pager"],
        environment=FakeEnvironment(interactive=False, tools={"git": "/g"}),
    )

    # And now the same decisions, answered at the prompts. Its own clone of the same
    # repository, because one branch cannot be checked out in two worktrees at once —
    # which is git's rule, not lane's, and not what this test is about.
    other_projects = tmp_path / "Projects-interactive"
    other_projects.mkdir()
    _repo(other_projects)
    other_lanes = tmp_path / "Lanes-interactive"
    ui = FakeUi(["demo", "new work", "Fix the pager", "branch", "other…", "x/pager"])
    interactive = Context(
        ui=ui,
        git=CliGitBackend(),
        github=StubGitHubClient(),
        environment=FakeEnvironment(tools={"git": "/g"}),
        config=Config(projects_root=other_projects, lanes_root=other_lanes, editor="cursor"),
        config_store=ConfigStore(tmp_path / "cfg2"),
        state_store=StateStore(tmp_path / "st2"),
    )
    open_lane.run(interactive)

    scripted = lanes_root / "demo" / "fix-the-pager"
    typed = other_lanes / "demo" / "fix-the-pager"
    assert git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=scripted).strip() == "x/pager"
    assert git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=typed).strip() == "x/pager"

    def meta(root: Path) -> LaneMeta:
        return LaneStore(root).read_meta("demo", "fix-the-pager")

    assert meta(lanes_root).description == meta(other_lanes).description == "Fix the pager"
    assert meta(lanes_root).base == meta(other_lanes).base


def test_open_missing_a_flag_with_no_terminal_names_what_is_missing_and_does_not_hang(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del xdg
    _repo(projects_root)
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["open", "--description", "Fix the pager"],
        environment=FakeEnvironment(interactive=False),
    )

    err = capsys.readouterr().err
    assert code == cli.EXIT_NO_TTY
    assert "--project" in err


def test_the_same_missing_flag_is_asked_for_when_there_is_a_terminal(
    xdg: Path, projects_root: Path, lanes_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TTY-gated, not flag-gated: with a terminal the real prompt asks, exactly as it
    would have in a session. Here the real `Ui` is replaced to stand in for one."""
    del xdg
    _repo(projects_root)
    _configured(projects_root, lanes_root)
    # Only the project is missing, so only the project is asked.
    answers = FakeUi(["demo"])
    monkeypatch.setattr(commands, "ConsoleUi", lambda **_: answers)

    code = cli.main(
        ["open", "--description", "Fix the pager", "--branch-name", "x/pager"],
        environment=FakeEnvironment(interactive=True, tools={"git": "/g"}),
    )

    assert code == cli.EXIT_OK
    assert answers.asked == ["Which project?"]
    assert (lanes_root / "demo" / "fix-the-pager" / ".git").exists()


def test_open_with_no_branch_name_takes_the_menus_own_first_entry(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """`feature/` is not written down in the command line's defaults: it is the first
    prefix the branch menu offers, which is a setting a team can change."""
    del xdg
    _repo(projects_root)
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["open", "--project", "demo", "--description", "Fix the pager"],
        environment=FakeEnvironment(interactive=False, tools={"git": "/g"}),
    )

    lane = lanes_root / "demo" / "fix-the-pager"
    assert code == cli.EXIT_OK
    assert git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=lane).strip() == "feature/fix-the-pager"


def test_open_as_json_reports_the_outcome_and_keeps_stdout_to_itself(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Everything lane says while opening — the summary, the `✓`, the push hint — is
    prose for a person, so it goes to stderr. stdout is the outcome and nothing else."""
    del xdg
    _repo(projects_root)
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["open", "--project", "demo", "--description", "Fix the pager", "--json"],
        environment=FakeEnvironment(interactive=False, tools={"git": "/g"}),
    )

    captured = capsys.readouterr()
    assert code == cli.EXIT_OK
    opened = json.loads(captured.out)
    assert opened["project"] == "demo"
    assert opened["lane"] == "fix-the-pager"
    assert opened["branch"] == "feature/fix-the-pager"
    assert opened["detached"] is False
    assert opened["path"].endswith(str(Path("demo") / "fix-the-pager"))
    assert len(opened["start"]) == 40
    assert opened["editor"]["launched"] is False

    assert "Lane open" in captured.err, "the prose is not suppressed, only moved"


def test_a_refusal_in_json_mode_still_leaves_stdout_parseable(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A script that cannot parse stdout cannot tell a refusal from a crash."""
    del xdg
    _repo(projects_root)
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["open", "--project", "nosuch", "--description", "x", "--json"],
        environment=FakeEnvironment(interactive=False, tools={"git": "/g"}),
    )

    captured = capsys.readouterr()
    assert code == cli.EXIT_NOT_FOUND
    assert captured.out == ""
    assert "nosuch" in captured.err


# -- enter -------------------------------------------------------------------------


def test_enter_takes_the_slug_the_listing_prints_and_prepares_the_lane(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """`project/lane` is the identifier the listing already shows everywhere. A script
    has no cursor, so it needs the one thing the interactive session never had to ask."""
    del xdg
    _a_lane(projects_root, lanes_root, ignore="junk/")
    _configured(projects_root, lanes_root)
    # An answer already on record, so there is nothing left to ask.
    PrepareStore(ConfigStore().path.parent).remember(
        "demo", [Step(project="demo", path="junk", verb=Verb.CLONE)]
    )

    code = cli.main(
        ["enter", "demo/pager"],
        environment=FakeEnvironment(interactive=False, tools={"git": "/g", "cursor": "/c"}),
    )

    assert code == cli.EXIT_OK
    assert (lanes_root / "demo" / "pager" / "junk" / "thing.txt").exists()


def test_enter_refuses_a_lane_that_is_not_there(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del xdg
    _a_lane(projects_root, lanes_root)
    _configured(projects_root, lanes_root)

    code = cli.main(["enter", "demo/nope"], environment=FakeEnvironment(interactive=False))

    err = capsys.readouterr().err
    assert code == cli.EXIT_NOT_FOUND
    assert "demo/nope" in err


def test_enter_refuses_a_name_that_is_not_project_slash_lane(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One identifier scheme, the one already printed. Not a bare name, however
    unambiguous it looks — a lane name is only unique inside its project."""
    del xdg
    _a_lane(projects_root, lanes_root)
    _configured(projects_root, lanes_root)

    code = cli.main(["enter", "pager"], environment=FakeEnvironment(interactive=False))

    err = capsys.readouterr().err
    assert code == cli.EXIT_USAGE
    assert "<project>/<lane>" in err


def test_entering_with_an_unanswered_path_and_no_terminal_refuses_before_doing_anything(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The decision this had to take, and why it is a refusal.

    Bringing an unanswered path in silently copies what nobody asked for — and a
    `.env` is exactly the kind of path that turns up unanswered. Leaving it out
    silently exits 0 on a lane that is *not* ready, which is a lie a script cannot
    detect. So it refuses, before applying anything, and says which paths it is about.
    """
    del xdg
    _a_lane(projects_root, lanes_root, ignore="junk/")
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["enter", "demo/pager"],
        environment=FakeEnvironment(interactive=False, tools={"git": "/g", "cursor": "/c"}),
    )

    err = capsys.readouterr().err
    assert code == cli.EXIT_NO_TTY
    assert "config" in err or "preparation" in err
    assert not (lanes_root / "demo" / "pager" / "junk").exists()


# -- close -------------------------------------------------------------------------
# The close screen is the one prompt whose rows are facts about *this* lane, so the
# flags are checked against the rows it would have drawn — not against a list written
# down here. The remote in these fixtures is a local path, so `gh` is never asked.


def _abandoned_branches(lane: Path) -> None:
    """A lane that moved through two branches and left unique work on each."""
    for branch, file in (("feature/second", "kept.txt"), ("feature/third", "dropped.txt")):
        git(["switch", "--quiet", "-c", branch], cwd=lane)
        (lane / file).write_text(f"work on {branch}\n")
        git(["add", "-A"], cwd=lane)
        git(["commit", "--quiet", "-m", f"work on {branch}"], cwd=lane)
    git(["switch", "--quiet", "feature/pager"], cwd=lane)


def test_close_with_yes_removes_the_lane(xdg: Path, projects_root: Path, lanes_root: Path) -> None:
    del xdg
    repo = _a_lane(projects_root, lanes_root)
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["close", "demo/pager", "--yes"], environment=FakeEnvironment(interactive=False)
    )

    assert code == cli.EXIT_OK
    assert not (lanes_root / "demo" / "pager").exists()
    assert not CliGitBackend().branch_exists(repo, "feature/pager")


def test_close_without_yes_and_without_a_terminal_refuses_and_leaves_the_lane(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Accepting the close is itself a decision, and no row flag makes it. `--yes` is
    the one that does, so a pipe that has not said it gets nothing done and told why."""
    del xdg
    _a_lane(projects_root, lanes_root)
    _configured(projects_root, lanes_root)

    code = cli.main(["close", "demo/pager"], environment=FakeEnvironment(interactive=False))

    err = capsys.readouterr().err
    assert code == cli.EXIT_NO_TTY
    assert "--yes" in err
    assert (lanes_root / "demo" / "pager").exists()


def test_a_row_flag_without_yes_is_refused_rather_than_half_applied(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Row flags say what closing does; `--yes` says to do it. Given one without the
    other there is no coherent half-state to fall into, so it is a usage error."""
    del xdg
    _a_lane(projects_root, lanes_root)
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["close", "demo/pager", "--keep-branch"], environment=FakeEnvironment(interactive=False)
    )

    err = capsys.readouterr().err
    assert code == cli.EXIT_USAGE
    assert "--delete-branch/--keep-branch says what closing does" in err
    assert "--yes" in err


def test_delete_others_keeps_one_branch_and_drops_another(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """The one thing the command line can do that a single question never could."""
    del xdg
    repo = _a_lane(projects_root, lanes_root)
    _abandoned_branches(lanes_root / "demo" / "pager")
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["close", "demo/pager", "--yes", "--delete-others", "feature/third"],
        environment=FakeEnvironment(interactive=False),
    )

    backend = CliGitBackend()
    assert code == cli.EXIT_OK
    assert backend.branch_exists(repo, "feature/second"), "not named, so not deleted"
    assert not backend.branch_exists(repo, "feature/third"), "named, so deleted"


def test_delete_others_naming_a_branch_this_close_never_offered_is_a_usage_error(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del xdg
    _a_lane(projects_root, lanes_root)
    _abandoned_branches(lanes_root / "demo" / "pager")
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["close", "demo/pager", "--yes", "--delete-others", "feature/nope"],
        environment=FakeEnvironment(interactive=False),
    )

    err = capsys.readouterr().err
    assert code == cli.EXIT_USAGE
    assert "feature/nope" in err
    assert "does not offer" in err, "refused by the close, against the rows it would draw"
    assert "feature/second" in err, "and it says which branches it does ask about"
    assert (lanes_root / "demo" / "pager").exists(), "refused before anything was removed"


def test_rescue_on_a_lane_with_nothing_to_rescue_is_a_usage_error(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Rescue keeps something that would otherwise be lost. Asking for it where nothing
    is at risk means the lane is not the one the caller thinks it is — worth saying."""
    del xdg
    _a_lane(projects_root, lanes_root)
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["close", "demo/pager", "--yes", "--rescue"], environment=FakeEnvironment(interactive=False)
    )

    err = capsys.readouterr().err
    assert code == cli.EXIT_USAGE
    assert "--rescue does not apply" in err
    assert (lanes_root / "demo" / "pager").exists()


def test_close_as_json_says_what_was_found_what_was_decided_and_what_happened(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del xdg
    _a_lane(projects_root, lanes_root)
    _abandoned_branches(lanes_root / "demo" / "pager")
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["close", "demo/pager", "--yes", "--json", "--delete-others", "feature/third"],
        environment=FakeEnvironment(interactive=False),
    )

    captured = capsys.readouterr()
    assert code == cli.EXIT_OK
    closed = json.loads(captured.out)
    assert closed["slug"] == "demo/pager"
    assert closed["closed"] is True
    assert closed["decided"]["delete_others"] == ["feature/third"]
    assert "feature/third" in closed["branches_deleted"]
    assert "feature/second" in closed["branches_kept"]
    assert isinstance(closed["found"]["issues"], list)


# -- one code path, asserted -------------------------------------------------------


def test_every_subcommand_runs_the_very_action_the_session_runs(
    xdg: Path, projects_root: Path, lanes_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rule this whole design exists to keep: **a subcommand does not do anything.**

    It answers the questions an action was going to ask and then runs that action. So
    each one is checked against the function the session itself calls — a subcommand
    growing its own version of opening or closing a lane shows up here, rather than in
    a bug report about the two behaving differently a year from now.
    """
    del xdg
    _a_lane(projects_root, lanes_root)
    _configured(projects_root, lanes_root)
    ran: list[str] = []

    def record(name: str, answer: object) -> object:
        ran.append(name)
        return answer

    monkeypatch.setattr(open_lane, "open_a_lane", lambda *_, **__: record("open", None))
    monkeypatch.setattr(
        enter_lane,
        "enter",
        lambda *_, **__: record("enter", enter_lane.Entered(launched=False, editor="")),
    )
    monkeypatch.setattr(
        close_lane,
        "close",
        lambda *_, **__: record("close", close_lane.Closed("demo/pager", closed=True)),
    )
    environment = FakeEnvironment(interactive=False, tools={"git": "/g"})

    cli.main(["open", "--project", "demo", "--description", "x"], environment=environment)
    cli.main(["enter", "demo/pager"], environment=environment)
    cli.main(["close", "demo/pager", "--yes"], environment=environment)

    assert ran == ["open", "enter", "close"]

    # And the menu's own table still names the same two it shares.
    by_key = {action.key: action.run for action in ACTIONS}
    assert by_key["open"] is open_lane.run
    assert by_key["list"] is list_lanes.run


# -- the exit-code table, one refusal each -----------------------------------------
# `list` and `doctor` have no refusal of their own: one is read-only and the other is
# the action that *explains* refusals, so it can never sit behind one. That is not a
# gap in the table — it is what those two commands are.


def test_open_refuses_when_there_is_nothing_to_open_a_lane_in(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A refusal, not a "no such project": the flag never gets consulted, because the
    projects folder has nothing in it that lane can open a lane in. Exit 1 says lane ran
    and would not; exit 4 is for a name that does not match something that does exist —
    which is what `--project nosuch` gets, above."""
    del xdg
    (projects_root / "demo").mkdir()  # a folder, not a repository
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["open", "--project", "demo", "--description", "x"],
        environment=FakeEnvironment(interactive=False, tools={"git": "/g"}),
    )

    # Without `--json` lane's own prose is the output, so it is on stdout. Only
    # `--json` moves it, and only because stdout is then the machine's channel.
    assert code == cli.EXIT_REFUSED
    assert "No projects in" in capsys.readouterr().out


def test_enter_reports_a_failed_preparation_step_as_a_refusal(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A failed step still leaves a usable lane — the exit code is what says it went
    wrong, because nothing else would in a pipe."""
    del xdg
    _a_lane(projects_root, lanes_root)
    _configured(projects_root, lanes_root)
    PrepareStore(ConfigStore().path.parent).remember(
        "demo", [Step(project="demo", verb=Verb.RUN, command="false")]
    )

    code = cli.main(
        ["enter", "demo/pager", "--json"],
        environment=FakeEnvironment(interactive=False, tools={"git": "/g"}),
    )

    captured = capsys.readouterr()
    assert code == cli.EXIT_REFUSED
    assert json.loads(captured.out)["prepared"]["failed"][0]["step"]


def test_close_refuses_when_it_cannot_work_out_what_to_check_against(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del xdg
    _a_lane(projects_root, lanes_root)
    _configured(projects_root, lanes_root)
    # Metadata pointing at something that is not a repository: there is no default
    # branch to check against, so the close refuses rather than guessing.
    LaneStore(lanes_root).write_meta(
        "demo", "pager", LaneMeta(description="pager", base="", repo=str(projects_root / "nope"))
    )

    code = cli.main(
        ["close", "demo/pager", "--yes", "--json"],
        environment=FakeEnvironment(interactive=False, tools={"git": "/g"}),
    )

    captured = capsys.readouterr()
    assert code == cli.EXIT_REFUSED
    assert json.loads(captured.out)["closed"] is False
    assert (lanes_root / "demo" / "pager").exists()


def test_json_is_accepted_before_the_subcommand_too(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`lane --json list` and `lane list --json` both read naturally, so both work."""
    del xdg
    _configured(projects_root, lanes_root)

    assert cli.main(["--json", "list"], environment=FakeEnvironment(interactive=False)) == 0

    assert json.loads(capsys.readouterr().out) == []


def test_a_config_that_cannot_be_read_refuses_every_subcommand(
    xdg: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one refusal that comes before any action runs — the same one the session
    gives, by the same route, because both are wired by `app.wire`."""
    store = ConfigStore()
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("this is not = valid = toml\n")
    del xdg

    code = cli.main(["list"], environment=FakeEnvironment(interactive=False))

    assert code == cli.EXIT_REFUSED
    assert "Fix or delete that file" in capsys.readouterr().out


def test_open_adopts_an_existing_branch_and_names_the_lane_after_it(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """The second path `open` has, from the command line: the branch is the choice, and
    the lane name defaults to what the prompt would have offered — its slug."""
    del xdg
    repo = _repo(projects_root)
    git(["branch", "feature/colleagues-work"], cwd=repo)
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["open", "--project", "demo", "--branch", "feature/colleagues-work"],
        environment=FakeEnvironment(interactive=False, tools={"git": "/g"}),
    )

    lane = lanes_root / "demo" / "feature-colleagues-work"
    assert code == cli.EXIT_OK
    assert git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=lane).strip() == "feature/colleagues-work"
    # The branch is the description, exactly as it is when picked from the list.
    assert LaneStore(lanes_root).read_meta("demo", "feature-colleagues-work").description == (
        "feature/colleagues-work"
    )


def test_lane_name_overrides_the_derived_one(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """A branch was named by somebody else for another purpose, so the forty-character
    cap cuts it where nobody chose. At a prompt you would edit it; here you pass it."""
    del xdg
    repo = _repo(projects_root)
    git(["branch", "feature/colleagues-work"], cwd=repo)
    _configured(projects_root, lanes_root)

    code = cli.main(
        [
            "open",
            "--project",
            "demo",
            "--branch",
            "feature/colleagues-work",
            "--lane-name",
            "review",
        ],
        environment=FakeEnvironment(interactive=False, tools={"git": "/g"}),
    )

    assert code == cli.EXIT_OK
    assert (lanes_root / "demo" / "review" / ".git").exists()


def test_open_detached_makes_a_lane_with_no_branch(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del xdg
    _repo(projects_root)
    _configured(projects_root, lanes_root)

    code = cli.main(
        [
            "open",
            "--project",
            "demo",
            "--description",
            "A look around",
            "--mode",
            "detached",
            "--json",
        ],
        environment=FakeEnvironment(interactive=False, tools={"git": "/g"}),
    )

    opened = json.loads(capsys.readouterr().out)
    assert code == cli.EXIT_OK
    assert opened["branch"] is None
    assert opened["detached"] is True

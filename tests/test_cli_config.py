"""`lane config` from the command line: the same screens, without a terminal.

Two things every one of these has to prove, and they are the same two the core-loop
subcommands prove (`test_cli_commands.py`):

1. **It runs the very code the screen runs.** `lane config set editor zed` answers the
   question `_ask_editor` was going to ask and then lets it ask it — same validation,
   same warning about an editor that is not on `PATH`, same write through the same
   `ConfigStore`. A second implementation of what a setting *means* would show up here.
2. **Missing or refused input is TTY-gated**, never a wait on stdin.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lane import cli
from lane.actions import config as config_screen
from lane.config import Config, ConfigStore
from lane.lanes import LaneMeta, LaneStore
from lane.prefixes import DEFAULT_PREFIXES, BranchPrefixStore
from lane.prepare import Step, Verb
from lane.prepare.store import PrepareStore
from tests.conftest import git
from tests.fakes import FakeEnvironment


def _configured(projects_root: Path, lanes_root: Path, *, editor: str = "cursor") -> None:
    """A real config file where `app.wire` will look for it."""
    ConfigStore().save(Config(projects_root=projects_root, lanes_root=lanes_root, editor=editor))


# -- get ---------------------------------------------------------------------------


def test_get_prints_one_setting_and_nothing_else(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del xdg
    _configured(projects_root, lanes_root, editor="zed")

    code = cli.main(["config", "get", "editor"], environment=FakeEnvironment(interactive=False))

    out = capsys.readouterr().out
    assert code == cli.EXIT_OK
    assert out.strip() == "zed", "one value, so it composes with $(…) without trimming"


def test_get_as_json_carries_the_key_the_value_and_the_override(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`overridden_by` is the field that makes a write checkable from a script."""
    del xdg
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["config", "get", "projects-root", "--json"],
        environment=FakeEnvironment(interactive=False),
    )

    report = json.loads(capsys.readouterr().out)
    assert code == cli.EXIT_OK
    assert report == {
        "key": "projects-root",
        "value": str(projects_root),
        "overridden_by": None,
    }


def test_get_says_null_for_a_setting_nothing_has_ever_set(
    xdg: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A path that is not set is `null`, never the empty string: a script has to be
    able to tell "unset" from "set to nothing", and only one of those is a real state."""
    del xdg
    ConfigStore().save(Config(projects_root=None, lanes_root=lanes_root, editor="cursor"))

    code = cli.main(
        ["config", "get", "projects-root", "--json"],
        environment=FakeEnvironment(interactive=False),
    )

    report = json.loads(capsys.readouterr().out)
    assert code == cli.EXIT_OK
    assert report["value"] is None


def test_get_reports_the_environment_variable_that_is_currently_winning(
    xdg: Path,
    projects_root: Path,
    lanes_root: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The screen says this in a dimmed suffix; a script reads it as a field."""
    del xdg
    _configured(projects_root, lanes_root, editor="cursor")
    monkeypatch.setenv("LANE_EDITOR", "zed")

    code = cli.main(
        ["config", "get", "editor", "--json"], environment=FakeEnvironment(interactive=False)
    )

    report = json.loads(capsys.readouterr().out)
    assert code == cli.EXIT_OK
    assert report["value"] == "zed", "what lane would actually use"
    assert report["overridden_by"] == "LANE_EDITOR"


def test_get_naming_nothing_is_a_usage_error_that_says_what_there_is(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del xdg
    _configured(projects_root, lanes_root)

    code = cli.main(["config", "get"], environment=FakeEnvironment(interactive=False))

    captured = capsys.readouterr()
    assert code == cli.EXIT_USAGE
    assert captured.out == "", "a refusal says nothing at all on stdout"
    assert "projects-root" in captured.err


# -- set ---------------------------------------------------------------------------


def test_set_writes_the_file_and_reports_the_new_value(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Through the real `ConfigStore`, exactly as choosing the row on screen does."""
    del xdg
    git(["init", "--quiet", str(projects_root / "p")])
    _configured(projects_root, lanes_root, editor="cursor")

    code = cli.main(
        ["config", "set", "editor", "zed"],
        environment=FakeEnvironment(interactive=False, tools={"git": "/g", "zed": "/z"}),
    )

    assert code == cli.EXIT_OK
    assert ConfigStore().load_file_only().editor == "zed"
    assert "zed" in capsys.readouterr().out


def test_set_leaves_the_other_two_settings_exactly_as_they_were(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """One row, one question, one write — the list screen's own property."""
    del xdg
    git(["init", "--quiet", str(projects_root / "p")])
    _configured(projects_root, lanes_root, editor="cursor")

    cli.main(
        ["config", "set", "editor", "zed"],
        environment=FakeEnvironment(interactive=False, tools={"git": "/g", "zed": "/z"}),
    )

    saved = ConfigStore().load_file_only()
    assert saved.projects_root == projects_root
    assert saved.lanes_root == lanes_root


def test_set_runs_the_screens_own_validation_and_refuses_a_root_with_no_repositories(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The refusal is `_ask_projects_root`'s, not a second copy of it — and because that
    function re-asks rather than returning, the value is *spent* and there is no terminal
    to ask in, which is exit 3 for the same reason `open --branch-name <bad>` is."""
    del xdg
    git(["init", "--quiet", str(projects_root / "p")])
    _configured(projects_root, lanes_root)
    empty = projects_root / "nothing-here"
    empty.mkdir()

    code = cli.main(
        ["config", "set", "projects-root", str(empty)],
        environment=FakeEnvironment(interactive=False),
    )

    captured = capsys.readouterr()
    assert code == cli.EXIT_NO_TTY
    # Without `--json` lane's own prose stays on stdout, so the screen's refusal is
    # there and the command line's is on stderr — as everywhere else.
    assert "none of its" in captured.out, "the screen's own wording, not a second refusal"
    assert "was not accepted" in captured.err
    assert ConfigStore().load_file_only().projects_root == projects_root, "nothing was written"


def test_set_writes_the_file_even_when_the_environment_is_winning_and_says_so(
    xdg: Path,
    projects_root: Path,
    lanes_root: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exactly what the screen already does. Saying so is what stops it looking like a
    bug — and `overridden_by` is what lets a script tell its write has not taken effect
    yet without reading prose."""
    del xdg
    _configured(projects_root, lanes_root, editor="cursor")
    monkeypatch.setenv("LANE_EDITOR", "vim")

    code = cli.main(
        ["config", "set", "editor", "zed", "--json"],
        environment=FakeEnvironment(interactive=False, tools={"git": "/g", "zed": "/z"}),
    )

    captured = capsys.readouterr()
    assert code == cli.EXIT_OK
    assert ConfigStore().load_file_only().editor == "zed", "the file took it"
    report = json.loads(captured.out)
    assert report["overridden_by"] == "LANE_EDITOR"
    assert report["value"] == "vim", "what lane would still use"
    assert "LANE_EDITOR" in captured.err, "and it is said in words too"


def test_set_on_a_machine_with_no_config_file_writes_one_without_the_first_run_walk(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """`config.run()` branches to the three-question sequence when there is no file.
    A subcommand must not: it was asked for one setting and given one answer, and
    walking it through the other two would be asking questions nobody invited."""
    del xdg
    assert not ConfigStore().path.exists()

    code = cli.main(
        ["config", "set", "editor", "zed"],
        environment=FakeEnvironment(interactive=False, tools={"git": "/g", "zed": "/z"}),
    )

    assert code == cli.EXIT_OK
    saved = ConfigStore().load_file_only()
    assert saved.editor == "zed"
    assert saved.projects_root is None, "it was not asked for, so it was not asked about"


def test_set_with_no_value_is_refused_by_name_rather_than_asked_for(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del xdg
    _configured(projects_root, lanes_root)

    code = cli.main(["config", "set", "editor"], environment=FakeEnvironment(interactive=False))

    captured = capsys.readouterr()
    assert code in {cli.EXIT_USAGE, cli.EXIT_NO_TTY}
    assert captured.out == ""
    assert ConfigStore().load_file_only().editor == "cursor"


# -- prefixes ----------------------------------------------------------------------


def test_prefixes_list_is_the_six_in_the_order_the_prompt_offers_them(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Never sorted: the order **is** the branch prompt's menu, so reporting it any
    other way would be describing a screen nobody sees."""
    del xdg
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["config", "prefixes", "list", "--json"], environment=FakeEnvironment(interactive=False)
    )

    report = json.loads(capsys.readouterr().out)
    assert code == cli.EXIT_OK
    assert report["prefixes"] == list(DEFAULT_PREFIXES)
    assert report["seeded"] is True, "nothing is customised, so these are the six"


def test_adding_a_prefix_keeps_the_six_and_appends_to_them(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The screen's rule, reached rather than repeated: adding `spike` is not a way to
    lose the six, and once anything is written the file *is* the menu."""
    del xdg
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["config", "prefixes", "add", "spike", "--json"],
        environment=FakeEnvironment(interactive=False),
    )

    report = json.loads(capsys.readouterr().out)
    assert code == cli.EXIT_OK
    assert BranchPrefixStore(ConfigStore().path.parent).load() == (*DEFAULT_PREFIXES, "spike")
    assert report["prefixes"][-1] == "spike"
    assert report["seeded"] is False


def test_a_prefix_git_would_not_take_is_refused_and_nothing_is_written(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """git owns this judgement — `_usable_prefix` asks it, here exactly as on screen."""
    del xdg
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["config", "prefixes", "add", ".."], environment=FakeEnvironment(interactive=False)
    )

    del capsys
    assert code == cli.EXIT_REFUSED
    assert not BranchPrefixStore(ConfigStore().path.parent).path.exists()


def test_adding_a_prefix_already_offered_is_refused_rather_than_duplicated(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """Two identical rows are two identical entries at the branch prompt, where picking
    either does the same thing — a menu that has stopped being a choice."""
    del xdg
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["config", "prefixes", "add", "feature"], environment=FakeEnvironment(interactive=False)
    )

    assert code == cli.EXIT_REFUSED


def test_changing_a_prefix_renames_it_in_place_rather_than_moving_it(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """The order is what the branch prompt shows, so a rename must not drop the row to
    the bottom of it — the screen's rule, and the reason `change` is not forget-and-add."""
    del xdg
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["config", "prefixes", "change", "bugfix", "defect"],
        environment=FakeEnvironment(interactive=False),
    )

    assert code == cli.EXIT_OK
    offered = BranchPrefixStore(ConfigStore().path.parent).load()
    assert offered.index("defect") == DEFAULT_PREFIXES.index("bugfix")


def test_forgetting_a_prefix_drops_it_and_leaves_the_rest_in_order(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    del xdg
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["config", "prefixes", "forget", "docs"], environment=FakeEnvironment(interactive=False)
    )

    assert code == cli.EXIT_OK
    assert BranchPrefixStore(ConfigStore().path.parent).load() == tuple(
        one for one in DEFAULT_PREFIXES if one != "docs"
    )


def test_a_prefix_that_is_not_offered_is_not_found_rather_than_quietly_ignored(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The screen resolves "which row" with a cursor; a script names it, so a name that
    is not there is the same kind of mistake as a lane that is not open."""
    del xdg
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["config", "prefixes", "forget", "nonesuch"],
        environment=FakeEnvironment(interactive=False),
    )

    assert code == cli.EXIT_NOT_FOUND
    assert "nonesuch" in capsys.readouterr().err


def test_forgetting_the_last_prefix_says_the_six_are_back(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty file means the seed, so the six reappear on the next prompt. Unexplained,
    that reads as the forget having failed — the screen says so, and so must this."""
    del xdg
    _configured(projects_root, lanes_root)
    BranchPrefixStore(ConfigStore().path.parent).save(["only"])

    code = cli.main(
        ["config", "prefixes", "forget", "only"], environment=FakeEnvironment(interactive=False)
    )

    assert code == cli.EXIT_OK
    assert "back" in capsys.readouterr().out


# -- one code path, and generated help ---------------------------------------------


def test_config_runs_the_very_functions_the_screen_runs(
    xdg: Path, projects_root: Path, lanes_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rule the whole design exists to keep, asserted for `config` as it already is
    for `open`/`enter`/`close`: a subcommand **answers** questions and runs the screen's
    own function. A second implementation of what a setting or a prefix means fails here
    rather than in a bug report about the two behaving differently."""
    del xdg
    _configured(projects_root, lanes_root)
    ran: list[str] = []

    def record(name: str, answer: bool) -> bool:
        ran.append(name)
        return answer

    monkeypatch.setattr(config_screen, "change_setting", lambda *_, **__: record("set", True))
    monkeypatch.setattr(config_screen, "add_prefix", lambda *_, **__: record("add", True))
    monkeypatch.setattr(config_screen, "act_on_prefix", lambda *_, **__: record("act", True))
    environment = FakeEnvironment(interactive=False)

    cli.main(["config", "set", "editor", "zed"], environment=environment)
    cli.main(["config", "prefixes", "add", "spike"], environment=environment)
    cli.main(["config", "prefixes", "forget", "docs"], environment=environment)

    assert ran == ["set", "add", "act"]


def test_help_is_generated_at_every_level_it_is_asked_at(
    xdg: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`lane config prefixes --help` is that screen's help, not `config`'s — argparse's
    rendering of the one definition that also parses it, at whatever depth was asked."""
    del xdg
    environment = FakeEnvironment(interactive=False)

    assert cli.main(["config", "--help"], environment=environment) == cli.EXIT_OK
    top = capsys.readouterr().out
    assert "prefixes" in top and "get" in top and "set" in top

    assert cli.main(["config", "prefixes", "--help"], environment=environment) == cli.EXIT_OK
    nested = capsys.readouterr().out
    assert "lane config prefixes" in nested
    assert "forget" in nested
    assert "print one setting's current value" not in nested, "one level's help, not its parent's"


# -- commands ----------------------------------------------------------------------


def _a_project(projects_root: Path, name: str = "demo") -> None:
    git(["init", "--quiet", str(projects_root / name)])


def test_commands_list_reports_one_projects_run_steps(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A `run` step carries three fields the screen lets you edit, so all three are here."""
    del xdg
    _a_project(projects_root)
    _configured(projects_root, lanes_root)
    PrepareStore(ConfigStore().path.parent).save(
        [
            Step(
                project="demo",
                verb=Verb.RUN,
                command="install",
                directory="web",
                unless="web/node_modules",
            ),
            Step(project="demo", verb=Verb.CLONE, path="node_modules"),
            Step(project="other", verb=Verb.RUN, command="elsewhere"),
        ]
    )

    code = cli.main(
        ["config", "commands", "list", "--project", "demo", "--json"],
        environment=FakeEnvironment(interactive=False),
    )

    report = json.loads(capsys.readouterr().out)
    assert code == cli.EXIT_OK
    assert report["commands"] == [
        {
            "id": "demo/install",
            "project": "demo",
            "command": "install",
            "directory": "web",
            "unless": "web/node_modules",
        }
    ], "this project's run steps, and neither its paths nor another project's"


def test_a_command_can_be_added_and_round_trips_through_the_store(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    del xdg
    _a_project(projects_root)
    _configured(projects_root, lanes_root)

    code = cli.main(
        [
            "config",
            "commands",
            "add",
            "--project",
            "demo",
            "--command",
            "install",
            "--directory",
            "web",
            "--unless",
            "web/node_modules",
        ],
        environment=FakeEnvironment(interactive=False),
    )

    assert code == cli.EXIT_OK
    step = PrepareStore(ConfigStore().path.parent).load().for_project("demo")[0]
    assert (step.verb, step.command, step.directory, step.unless) == (
        Verb.RUN,
        "install",
        "web",
        "web/node_modules",
    )


def test_changing_one_field_leaves_the_others_exactly_as_they_were(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """The screen re-asks all three with each defaulted to its stored value, so pressing
    Enter keeps it. `change` supplies the field it was given and takes the prompt's own
    default for the rest — which is that behaviour reached, not a second notion of
    "changed"."""
    del xdg
    _a_project(projects_root)
    _configured(projects_root, lanes_root)
    PrepareStore(ConfigStore().path.parent).save(
        [
            Step(
                project="demo",
                verb=Verb.RUN,
                command="install",
                directory="web",
                unless="web/node_modules",
            )
        ]
    )

    code = cli.main(
        ["config", "commands", "change", "demo/install", "--directory", "api"],
        environment=FakeEnvironment(interactive=False),
    )

    assert code == cli.EXIT_OK
    step = PrepareStore(ConfigStore().path.parent).load().for_project("demo")[0]
    assert step.directory == "api"
    assert step.command == "install", "not given, so not changed"
    assert step.unless == "web/node_modules", "not given, so not changed"


def test_a_command_with_a_slash_in_it_is_still_one_identifier(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """`<project>/<command>` splits on the **first** slash and takes the rest verbatim.

    A lane name containing a slash is refused, because a lane name cannot have one. A
    command routinely does — `bin/install` — so the same identifier shape needs one
    clause different, and that difference is this test."""
    del xdg
    _a_project(projects_root)
    _configured(projects_root, lanes_root)
    PrepareStore(ConfigStore().path.parent).save(
        [Step(project="demo", verb=Verb.RUN, command="bin/install things")]
    )

    code = cli.main(
        ["config", "commands", "forget", "demo/bin/install things"],
        environment=FakeEnvironment(interactive=False),
    )

    assert code == cli.EXIT_OK
    assert PrepareStore(ConfigStore().path.parent).load().for_project("demo") == ()


def test_forgetting_a_command_leaves_the_paths_alone(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    del xdg
    _a_project(projects_root)
    _configured(projects_root, lanes_root)
    PrepareStore(ConfigStore().path.parent).save(
        [
            Step(project="demo", verb=Verb.RUN, command="install"),
            Step(project="demo", verb=Verb.CLONE, path="node_modules"),
        ]
    )

    code = cli.main(
        ["config", "commands", "forget", "demo/install"],
        environment=FakeEnvironment(interactive=False),
    )

    assert code == cli.EXIT_OK
    remaining = PrepareStore(ConfigStore().path.parent).load().for_project("demo")
    assert [step.path for step in remaining] == ["node_modules"]


def test_a_command_that_is_not_stored_is_not_found(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    del xdg
    _a_project(projects_root)
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["config", "commands", "forget", "demo/nothing"],
        environment=FakeEnvironment(interactive=False),
    )

    assert code == cli.EXIT_NOT_FOUND
    assert "nothing" in capsys.readouterr().err


def test_a_project_that_does_not_exist_is_not_found(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--project` names a project, and a name that is not there is the same kind of
    mistake as a lane that is not open."""
    del xdg
    _a_project(projects_root)
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["config", "commands", "list", "--project", "nonesuch"],
        environment=FakeEnvironment(interactive=False),
    )

    assert code == cli.EXIT_NOT_FOUND
    assert "nonesuch" in capsys.readouterr().err


# -- preparation -------------------------------------------------------------------


def _a_project_with_ignored(projects_root: Path, *names: str) -> Path:
    """A real repository ignoring each `name/`, with each directory actually there.

    The names here are what **git reports**, which is the unslashed form — a fully
    ignored directory is `node_modules` in `ls-files -o -i --directory` output even
    though `.gitignore` says `node_modules/`. That is the spelling every answer is
    stored under, so it is the spelling the command line takes.
    """
    repo = projects_root / "demo"
    git(["init", "--quiet", str(repo)])
    git(["config", "user.email", "t@example.invalid"], cwd=repo)
    git(["config", "user.name", "t"], cwd=repo)
    (repo / ".gitignore").write_text("".join(f"{name}/\n" for name in names))
    git(["add", ".gitignore"], cwd=repo)
    git(["commit", "--quiet", "-m", "ignore"], cwd=repo)
    for name in names:
        (repo / name).mkdir(parents=True, exist_ok=True)
        (repo / name / "thing.txt").write_text("x\n")
    return repo


def test_preparation_list_says_in_out_and_unset_for_each_path(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The tri-state the checklist uses, as data: a stored `skip` is `out` and a path
    nobody has answered is `unset` — the distinction two states could not make."""
    del xdg
    _a_project_with_ignored(projects_root, "node_modules", "build", "cache")
    _configured(projects_root, lanes_root)
    PrepareStore(ConfigStore().path.parent).save(
        [
            Step(project="demo", verb=Verb.CLONE, path="node_modules"),
            Step(project="demo", verb=Verb.SKIP, path="build"),
        ]
    )

    code = cli.main(
        ["config", "preparation", "list", "--project", "demo", "--json"],
        environment=FakeEnvironment(interactive=False),
    )

    report = json.loads(capsys.readouterr().out)
    assert code == cli.EXIT_OK
    answers = {one["path"]: one["answer"] for one in report["paths"]}
    assert answers["node_modules"] == "in"
    assert answers["build"] == "out"
    assert answers["cache"] == "unset", "discovered, never answered"


def test_preparation_list_says_whether_a_path_is_in_an_open_lane(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A tick that copies a gigabyte and a tick that does nothing have to look different,
    and with no lane in hand the screen cannot say it — a script can be told."""
    del xdg
    repo = _a_project_with_ignored(projects_root, "node_modules", "build")
    _configured(projects_root, lanes_root)
    # A real worktree, because that is what the listing counts as an open lane — a bare
    # directory under the lanes root is not one, and asserting against a fake would be
    # asserting against something lane would never see.
    store = LaneStore(lanes_root)
    lane = store.lane_path("demo", "pager")
    lane.parent.mkdir(parents=True, exist_ok=True)
    git(["worktree", "add", "--quiet", str(lane), "-b", "feature/pager", "HEAD"], cwd=repo)
    store.write_meta(
        "demo", "pager", LaneMeta(description="pager", base="main", repo=str(repo), start="")
    )
    (lane / "node_modules").mkdir(parents=True)

    cli.main(
        ["config", "preparation", "list", "--project", "demo", "--json"],
        environment=FakeEnvironment(interactive=False),
    )

    report = json.loads(capsys.readouterr().out)
    present = {one["path"]: one["present_in_a_lane"] for one in report["paths"]}
    assert present["node_modules"] is True
    assert present["build"] is False


def test_one_path_can_be_answered_and_round_trips_through_the_store(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    del xdg
    _a_project_with_ignored(projects_root, "node_modules")
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["config", "preparation", "set", "--project", "demo", "--path", "node_modules", "--in"],
        environment=FakeEnvironment(interactive=False),
    )

    assert code == cli.EXIT_OK
    steps = PrepareStore(ConfigStore().path.parent).load().for_project("demo")
    assert [(step.path, step.verb) for step in steps] == [("node_modules", Verb.CLONE)]


def test_a_batch_applies_every_valid_entry_in_one_write(
    xdg: Path,
    projects_root: Path,
    lanes_root: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The screen's own rule (`prepare/store.py`, "one write, not one per path"), and the
    reason `--from-json` exists: two hundred paths answered one invocation each is parity
    on paper and unusable in practice."""
    del xdg
    _a_project_with_ignored(projects_root, "node_modules", "build", "cache")
    _configured(projects_root, lanes_root)
    batch = projects_root / "answers.json"
    batch.write_text(
        json.dumps(
            [
                {"path": "node_modules", "answer": "in"},
                {"path": "build", "answer": "out"},
                {"path": "cache", "answer": "in"},
            ]
        )
    )
    writes: list[int] = []
    real = PrepareStore.save

    def counted(self: PrepareStore, steps: object) -> None:
        writes.append(1)
        real(self, steps)  # type: ignore[arg-type]

    monkeypatch.setattr(PrepareStore, "save", counted)

    code = cli.main(
        ["config", "preparation", "set", "--project", "demo", "--from-json", str(batch), "--json"],
        environment=FakeEnvironment(interactive=False),
    )

    report = json.loads(capsys.readouterr().out)
    assert code == cli.EXIT_OK
    assert len(writes) == 1, "one write, not one per path"
    assert len(report["applied"]) == 3
    assert report["rejected"] == []


def test_a_batch_with_a_typo_applies_the_rest_and_reports_that_one(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """ "Some of two hundred were typos" is the case a batch tool has to answer usefully:
    the good ones land, the bad ones are named one by one, and the file is never left
    half-written."""
    del xdg
    _a_project_with_ignored(projects_root, "node_modules", "build")
    _configured(projects_root, lanes_root)
    batch = projects_root / "answers.json"
    batch.write_text(
        json.dumps(
            [
                {"path": "node_modules", "answer": "in"},
                {"path": "ndoe_modules", "answer": "in"},
                {"path": "build", "answer": "out"},
            ]
        )
    )

    code = cli.main(
        ["config", "preparation", "set", "--project", "demo", "--from-json", str(batch), "--json"],
        environment=FakeEnvironment(interactive=False),
    )

    report = json.loads(capsys.readouterr().out)
    assert code == cli.EXIT_REFUSED, "something was refused, so it did not all happen"
    assert [one["path"] for one in report["applied"]] == ["node_modules", "build"]
    assert [one["path"] for one in report["rejected"]] == ["ndoe_modules"]

    stored = PrepareStore(ConfigStore().path.parent).load().for_project("demo")
    assert {step.path for step in stored} == {"node_modules", "build"}, "no half-written file"


def test_a_batch_where_everything_is_a_typo_writes_nothing_at_all(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    del xdg
    _a_project_with_ignored(projects_root, "node_modules")
    _configured(projects_root, lanes_root)
    batch = projects_root / "answers.json"
    batch.write_text(json.dumps([{"path": "nope", "answer": "in"}]))

    code = cli.main(
        ["config", "preparation", "set", "--project", "demo", "--from-json", str(batch)],
        environment=FakeEnvironment(interactive=False),
    )

    assert code == cli.EXIT_REFUSED
    assert not PrepareStore(ConfigStore().path.parent).path.exists()


def test_a_batch_can_be_read_from_stdin(
    xdg: Path,
    projects_root: Path,
    lanes_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`-` is the shell convention, and the point of a batch is that it is generated."""
    import io

    del xdg
    _a_project_with_ignored(projects_root, "node_modules")
    _configured(projects_root, lanes_root)
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(json.dumps([{"path": "node_modules", "answer": "in"}]))
    )

    code = cli.main(
        ["config", "preparation", "set", "--project", "demo", "--from-json", "-"],
        environment=FakeEnvironment(interactive=False),
    )

    assert code == cli.EXIT_OK
    assert PrepareStore(ConfigStore().path.parent).load().for_project("demo")[0].verb is Verb.CLONE


def test_answering_one_path_leaves_every_other_projects_answers_alone(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """One project at a time, like `remember` — this must never be a whole-file rewrite."""
    del xdg
    _a_project_with_ignored(projects_root, "node_modules")
    _configured(projects_root, lanes_root)
    PrepareStore(ConfigStore().path.parent).save(
        [
            Step(project="other", verb=Verb.CLONE, path="vendor"),
            Step(project="other", verb=Verb.RUN, command="install"),
        ]
    )

    cli.main(
        ["config", "preparation", "set", "--project", "demo", "--path", "node_modules", "--out"],
        environment=FakeEnvironment(interactive=False),
    )

    remembered = PrepareStore(ConfigStore().path.parent).load()
    assert len(remembered.for_project("other")) == 2
    assert remembered.for_project("demo")[0].verb is Verb.SKIP


def test_set_with_neither_in_nor_out_is_a_usage_error(
    xdg: Path, projects_root: Path, lanes_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A path is in or out and nothing else; "set it to nothing" is not one of the three
    states — an unanswered path has no step at all, which is a deletion, not a `set`."""
    del xdg
    _a_project_with_ignored(projects_root, "node_modules")
    _configured(projects_root, lanes_root)

    code = cli.main(
        ["config", "preparation", "set", "--project", "demo", "--path", "node_modules"],
        environment=FakeEnvironment(interactive=False),
    )

    del capsys
    assert code == cli.EXIT_USAGE
    assert not PrepareStore(ConfigStore().path.parent).path.exists()

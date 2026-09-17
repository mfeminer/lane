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
from lane.prefixes import DEFAULT_PREFIXES, BranchPrefixStore
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

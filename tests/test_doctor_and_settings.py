"""Doctor and settings.

The listing moved to `test_listing.py` when it became a screen of its own.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lane.actions import doctor, open_lane, settings
from lane.config import Config, ConfigStore
from lane.context import Context
from lane.git.cli_backend import CliGitBackend
from lane.lanes import LaneStore
from lane.prefixes import DEFAULT_PREFIXES, BranchPrefixStore
from lane.prepare import Candidate, Step, Verb, apply
from lane.prepare.sheet import Sheet, answers_from
from lane.state import StateStore
from lane.ui.checklist import paint
from tests.conftest import build_repo, git
from tests.fakes import FakeEnvironment, FakeUi, StubGitHubClient


def _context(
    ui: FakeUi,
    *,
    projects_root: Path | None,
    lanes_root: Path,
    environment: FakeEnvironment | None = None,
    github: StubGitHubClient | None = None,
    editor: str = "cursor",
    config_dir: Path | None = None,
) -> Context:
    return Context(
        ui=ui,
        git=CliGitBackend(),
        github=github or StubGitHubClient(),
        environment=environment or FakeEnvironment(tools={"git": "/g", "cursor": "/c"}),
        config=Config(projects_root=projects_root, lanes_root=lanes_root, editor=editor),
        config_store=ConfigStore(config_dir or lanes_root.parent / "cfg"),
        state_store=StateStore(lanes_root.parent / "st"),
    )


# -- D5, D6, I29: doctor ---------------------------------------------------------


def test_doctor_reports_the_running_binary_and_its_fingerprint(
    projects_root: Path, lanes_root: Path
) -> None:
    """Under PyInstaller, __file__ is a temp dir — sys.executable is the binary."""
    import sys

    ui = FakeUi([])
    doctor.run(_context(ui, projects_root=projects_root, lanes_root=lanes_root))

    assert ui.said("Running:")
    assert ui.said(sys.executable)
    assert ui.said("build")
    assert ui.said("which -a lane")


def test_doctor_renders_its_whole_report_when_nothing_is_installed(
    projects_root: Path, lanes_root: Path
) -> None:
    """The one action that must work on a machine with none of its prerequisites."""
    ui = FakeUi([])
    bare = FakeEnvironment(tools={})  # no git, no gh, no editor

    doctor.run(
        _context(ui, projects_root=None, lanes_root=lanes_root, environment=bare, editor="cursor")
    )

    assert ui.said("git is not installed")
    assert ui.said("GitHub CLI is not installed")
    assert ui.said("Projects folder is not set")
    assert ui.said("Editor not found")
    # It got all the way to the end rather than stopping at the first absence.
    assert ui.said("Running:")


def test_doctor_says_how_to_install_gh_and_that_everything_else_still_works(
    projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi([])
    no_gh = FakeEnvironment(tools={"git": "/g", "cursor": "/c"})

    doctor.run(_context(ui, projects_root=projects_root, lanes_root=lanes_root, environment=no_gh))

    assert ui.said("brew install gh")
    assert ui.said("Everything else")


def test_doctor_flags_gh_installed_but_logged_out(projects_root: Path, lanes_root: Path) -> None:
    class LoggedOut(FakeEnvironment):
        def tool_version(self, tool: str, *args: str) -> str | None:
            if tool == "gh" and args[:1] == ("auth",):
                return None  # `gh auth status` fails
            return super().tool_version(tool, *args)

    ui = FakeUi([])
    doctor.run(
        _context(
            ui,
            projects_root=projects_root,
            lanes_root=lanes_root,
            environment=LoggedOut(tools={"git": "/g", "gh": "/gh", "cursor": "/c"}),
        )
    )

    assert ui.said("not logged in")
    assert ui.said("gh auth login")


def test_doctor_counts_projects_and_open_lanes(projects_root: Path, lanes_root: Path) -> None:
    _origin, clone = build_repo(projects_root / "_b")
    repo = projects_root / "thing"
    clone.rename(repo)
    store = LaneStore(lanes_root)
    CliGitBackend().add_worktree_detached(repo, store.lane_path("thing", "l1"), "origin/main")

    ui = FakeUi([])
    doctor.run(_context(ui, projects_root=projects_root, lanes_root=lanes_root))

    assert ui.said("1 repos")
    assert ui.said("1 open")


def test_doctor_points_at_a_nested_layout(projects_root: Path, lanes_root: Path) -> None:
    org = projects_root / "acme"
    org.mkdir()
    git(["init", "--quiet", str(org / "Acme.Widgets")])

    ui = FakeUi([])
    doctor.run(_context(ui, projects_root=projects_root, lanes_root=lanes_root))

    assert ui.said("nested")
    assert ui.said(str(org))


def test_doctor_names_an_environment_override(projects_root: Path, lanes_root: Path) -> None:
    ui = FakeUi([])
    context = _context(ui, projects_root=projects_root, lanes_root=lanes_root)
    context.overridden = {"editor": "LANE_EDITOR"}

    doctor.run(context)

    assert ui.said("LANE_EDITOR overrides editor")


# -- E9, I28: settings -----------------------------------------------------------


def test_settings_saves_the_three_values(xdg: Path, projects_root: Path, lanes_root: Path) -> None:
    git(["init", "--quiet", str(projects_root / "a-project")])
    config_dir = xdg / "cfg"
    ui = FakeUi([str(projects_root), str(lanes_root), "zed"])
    context = _context(
        ui,
        projects_root=None,
        lanes_root=lanes_root,
        config_dir=config_dir,
        environment=FakeEnvironment(tools={"git": "/g", "zed": "/z"}),
    )

    settings.run(context)

    saved = ConfigStore(config_dir).load_file_only()
    assert saved.projects_root == projects_root
    assert saved.lanes_root == lanes_root
    assert saved.editor == "zed"
    assert ui.said("Saved to")


def test_settings_refuses_a_projects_folder_with_no_repositories(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """Everything depends on this being right, so it is checked before moving on."""
    empty = projects_root / "empty"
    empty.mkdir()
    (empty / "just-a-folder").mkdir()
    git(["init", "--quiet", str(projects_root / "real")])

    ui = FakeUi([str(empty), str(projects_root), str(lanes_root), "cursor"])
    context = _context(ui, projects_root=None, lanes_root=lanes_root, config_dir=xdg / "cfg2")

    settings.run(context)

    assert ui.said("none of its")
    assert ConfigStore(xdg / "cfg2").load_file_only().projects_root == projects_root


def test_settings_says_plainly_when_the_environment_is_winning(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """Otherwise saving a value that does not take effect looks like a bug."""
    git(["init", "--quiet", str(projects_root / "p")])
    ui = FakeUi([str(projects_root), str(lanes_root), "cursor"])
    context = _context(ui, projects_root=None, lanes_root=lanes_root, config_dir=xdg / "cfg3")
    context.overridden = {"editor": "LANE_EDITOR"}

    settings.run(context)

    assert ui.said("environment is currently winning")
    assert ui.said("LANE_EDITOR overrides editor")
    assert ui.said("saved to the file")


def test_settings_warns_when_lanes_would_sit_inside_the_projects_folder(
    xdg: Path, projects_root: Path
) -> None:
    git(["init", "--quiet", str(projects_root / "p")])
    inside = projects_root / "Lanes"
    ui = FakeUi([str(projects_root), str(inside), "cursor"])
    context = _context(ui, projects_root=None, lanes_root=inside, config_dir=xdg / "cfg4")

    settings.run(context)

    assert ui.said("inside your projects folder")


def test_settings_notes_an_editor_that_is_not_on_path(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    git(["init", "--quiet", str(projects_root / "p")])
    ui = FakeUi([str(projects_root), str(lanes_root), "nonexistent-editor"])
    context = _context(ui, projects_root=None, lanes_root=lanes_root, config_dir=xdg / "cfg5")

    settings.run(context)

    assert ui.said("is not on your PATH")
    # It is still saved: lanes open regardless, the editor just will not launch.
    assert ConfigStore(xdg / "cfg5").load_file_only().editor == "nonexistent-editor"


# -- E-series: the lanes folder default -----------------------------------------


def test_the_lanes_default_is_offered_next_to_the_projects_folder(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """After choosing /x/y/projects, the obvious place for lanes is /x/y/Lanes.

    Offering $HOME/Lanes meant retyping a path you had just implied.
    """
    git(["init", "--quiet", str(projects_root / "p")])
    offered: list[str] = []

    class Recording(FakeUi):
        def text(self, title, *, default=""):  # type: ignore[no-untyped-def]
            if "lanes be parked" in title:
                offered.append(default)
            return super().text(title, default=default)

    # Answer the lanes question with "" so the default is taken.
    ui = Recording([str(projects_root), "", "cursor"])
    context = _context(ui, projects_root=None, lanes_root=lanes_root, config_dir=xdg / "cfgL")

    settings.run(context)

    assert offered == [str(projects_root.parent / "Lanes")]
    saved = ConfigStore(xdg / "cfgL").load_file_only()
    assert saved.lanes_root == projects_root.parent / "Lanes"


def test_an_already_configured_lanes_folder_is_offered_instead(
    xdg: Path, projects_root: Path, tmp_path: Path
) -> None:
    """A choice you have already made is never quietly replaced by a suggestion.

    A config file already exists here, so this now goes through the settings list
    rather than the first-run sequence: pick the "lanes root" row, answer "" to keep
    the suggested default, and check what was actually suggested.
    """
    git(["init", "--quiet", str(projects_root / "p")])
    config_dir = xdg / "cfgM"
    chosen = tmp_path / "MyOwnLanes"
    ConfigStore(config_dir).save(
        Config(projects_root=projects_root, lanes_root=chosen, editor="cursor")
    )

    offered: list[str] = []

    class Recording(FakeUi):
        def text(self, title, *, default=""):  # type: ignore[no-untyped-def]
            if "lanes be parked" in title:
                offered.append(default)
            return super().text(title, default=default)

    ui = Recording(["lanes root", "", "back"])
    context = _context(ui, projects_root=projects_root, lanes_root=chosen, config_dir=config_dir)

    settings.run(context)

    assert offered == [str(chosen)]
    assert ConfigStore(config_dir).load_file_only().lanes_root == chosen


def test_the_lanes_folder_can_still_be_changed_to_anything(
    xdg: Path, projects_root: Path, tmp_path: Path
) -> None:
    git(["init", "--quiet", str(projects_root / "p")])
    elsewhere = tmp_path / "somewhere" / "else"
    ui = FakeUi([str(projects_root), str(elsewhere), "cursor"])
    context = _context(ui, projects_root=None, lanes_root=elsewhere, config_dir=xdg / "cfgN")

    settings.run(context)

    assert ConfigStore(xdg / "cfgN").load_file_only().lanes_root == elsewhere


# -- L8: settings redesigned as a list, acted on one setting at a time ----------


def test_a_fresh_run_with_no_config_file_gets_the_fixed_sequence_not_the_list(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """`store.path.exists()` is False: nothing works until all three are set, so
    there is no "current value" list to show — the old fixed script runs, unchanged."""
    git(["init", "--quiet", str(projects_root / "p")])
    config_dir = xdg / "cfgFirst"
    assert not ConfigStore(config_dir).path.exists()
    ui = FakeUi([str(projects_root), str(lanes_root), "cursor"])
    context = _context(ui, projects_root=None, lanes_root=lanes_root, config_dir=config_dir)

    settings.run(context)

    # Three plain text questions, in order, and nothing that looks like a table.
    assert not any(told.kind == "table" for told in ui.told)
    assert ui.unanswered() == 0
    saved = ConfigStore(config_dir).load_file_only()
    assert saved.projects_root == projects_root
    assert saved.lanes_root == lanes_root
    assert saved.editor == "cursor"


def test_an_existing_config_shows_the_list_instead_of_the_fixed_sequence(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """Config already on disk: a list of the three settings and their current
    values, not another unconditional walk through all three."""
    git(["init", "--quiet", str(projects_root / "p")])
    config_dir = xdg / "cfgListShape"
    ConfigStore(config_dir).save(
        Config(projects_root=projects_root, lanes_root=lanes_root, editor="cursor")
    )

    ui = FakeUi(["back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )

    settings.run(context)

    titles = [told.text for told in ui.told if told.kind == "table"]
    assert titles == ["lane settings"]
    rows = [told.text for told in ui.told if told.kind == "row"]
    assert any("projects root" in row and str(projects_root) in row for row in rows)
    assert any("lanes root" in row and str(lanes_root) in row for row in rows)
    assert any("editor" in row and "cursor" in row for row in rows)


def test_choosing_the_editor_row_asks_only_that_one_question_and_saves_it(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """Driven exactly like the lanes table's row-menu tests: pick a row, answer its
    one question, and land back on the (updated) list."""
    git(["init", "--quiet", str(projects_root / "p")])
    config_dir = xdg / "cfgOneRow"
    ConfigStore(config_dir).save(
        Config(projects_root=projects_root, lanes_root=lanes_root, editor="cursor")
    )

    ui = FakeUi(["editor", "zed", "back"])
    context = _context(
        ui,
        projects_root=projects_root,
        lanes_root=lanes_root,
        config_dir=config_dir,
        environment=FakeEnvironment(tools={"git": "/g", "zed": "/z"}),
    )

    settings.run(context)

    assert ConfigStore(config_dir).load_file_only().editor == "zed"
    # The other two settings were untouched — only one question was asked.
    assert ConfigStore(config_dir).load_file_only().projects_root == projects_root
    assert ConfigStore(config_dir).load_file_only().lanes_root == lanes_root
    assert ui.unanswered() == 0
    titles = [told.text for told in ui.told if told.kind == "table"]
    assert titles == ["lane settings", "lane settings"], "back to the updated list, not the menu"


def test_the_projects_root_question_reuses_todays_validation_from_the_list(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """A projects root with no repositories is still refused, from the list too."""
    empty = projects_root / "empty"
    empty.mkdir()
    git(["init", "--quiet", str(projects_root / "real")])
    config_dir = xdg / "cfgRowValidate"
    ConfigStore(config_dir).save(
        Config(projects_root=projects_root, lanes_root=lanes_root, editor="cursor")
    )

    ui = FakeUi(["projects root", str(empty), str(projects_root), "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )

    settings.run(context)

    assert ui.said("none of its")
    assert ConfigStore(config_dir).load_file_only().projects_root == projects_root


def test_after_each_setting_is_saved_the_context_is_reloaded(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """Save happens immediately per setting, exactly as the old flow did, wired
    through `context.reload_config()` — not batched until the whole list is left."""
    git(["init", "--quiet", str(projects_root / "p")])
    config_dir = xdg / "cfgReload"
    ConfigStore(config_dir).save(
        Config(projects_root=projects_root, lanes_root=lanes_root, editor="cursor")
    )

    ui = FakeUi(["editor", "zed", "back"])
    context = _context(
        ui,
        projects_root=projects_root,
        lanes_root=lanes_root,
        config_dir=config_dir,
        environment=FakeEnvironment(tools={"git": "/g", "zed": "/z"}),
    )

    settings.run(context)

    assert context.config.editor == "zed", "the live context picked up the new value"


def test_an_environment_override_is_visible_in_the_list(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """Adapting today's "environment is currently winning" messaging to the list."""
    config_dir = xdg / "cfgOverrideList"
    ConfigStore(config_dir).save(
        Config(projects_root=projects_root, lanes_root=lanes_root, editor="cursor")
    )

    ui = FakeUi(["back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )
    context.overridden = {"editor": "LANE_EDITOR"}

    settings.run(context)

    assert ui.said("environment is currently winning")
    assert ui.said("LANE_EDITOR overrides editor")
    rows = [told.text for told in ui.told if told.kind == "row"]
    assert any("overridden by LANE_EDITOR" in row for row in rows)


# -- preparation, from settings --------------------------------------------------


def _configured(xdg: Path, projects_root: Path, lanes_root: Path, name: str) -> Path:
    """A config already on disk, so settings shows its list rather than the first run."""
    config_dir = xdg / name
    git(["init", "--quiet", str(projects_root / "p")])
    ConfigStore(config_dir).save(
        Config(projects_root=projects_root, lanes_root=lanes_root, editor="cursor")
    )
    return config_dir


def test_settings_has_a_preparation_row_saying_how_much_is_in(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgP1")
    ui = FakeUi(["back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )
    context.prepare_store().save(
        (
            Step(project="acme", verb=Verb.CLONE, path="node_modules"),
            Step(project="other", verb=Verb.SKIP, path="vendor"),
        )
    )

    settings.run(context)

    rows = [told.text for told in ui.told if told.kind == "row"]
    assert any("preparation" in row and "1 path in, 1 out" in row for row in rows)


def test_settings_tells_a_stored_skip_from_a_path_nobody_has_answered(
    projects_root: Path,
) -> None:
    """The gap the two-state screen left, and the one settings felt worst.

    Settings reviews *stored decisions*, so "kept out on purpose" is a normal thing for a
    row there to be — and it drew as a blank gutter, exactly like a path that had never
    been asked about. Three states, three marks, and the mark is what says it rather than
    the colour (§6).

    Driven through the real widget rather than the fake: marks are what is being claimed,
    and `FakeUi` records cell text with no gutter at all.
    """
    steps = (
        Step(project="acme", verb=Verb.CLONE, path="a/kept"),
        Step(project="acme", verb=Verb.SKIP, path="b/refused"),
    )
    never_asked = Candidate(path="c/unasked", project="acme")
    sheet = Sheet(
        [*(Candidate(path=step.path, project=step.project) for step in steps), never_asked],
        source=lambda one: projects_root / one.project / one.path,
        stored=answers_from(steps),
        lead=True,
    )

    lines = paint(
        "3 answered paths in 1 project",
        sheet.columns,
        sheet.rows(),
        answers=sheet.answers,
        cursor=0,
        top=0,
        width=120,
        height=40,
    ).lines
    marks = {
        name: next(line for line in lines if name in line)[:4]
        for name in ("kept", "refused", "unasked")
    }

    assert "✓" in marks["kept"]
    assert "✗" in marks["refused"]
    assert "○" in marks["unasked"]
    assert len({mark.strip() for mark in marks.values()}) == 3, marks


def test_settings_opens_the_same_screen_entering_a_lane_does(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """One component, two callers — asserted on the call rather than on resemblance,
    because resemblance is exactly what drifts."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgP2")
    ui = FakeUi(["preparation", [], "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )
    context.prepare_store().save((Step(project="acme", verb=Verb.CLONE, path="node_modules"),))

    settings.run(context)

    assert ui.checklists == 1, "the checklist, not a table of rows you go into"


def test_the_preparation_screen_shows_every_projects_paths_with_the_project_dimmed(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """One screen for every project rather than a project list and then a page each: the
    lanes table already solves "rows from several projects in one table" with a dimmed
    lead, so this is two levels of nesting instead of three."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgP3")
    ui = FakeUi(["preparation", [], "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )
    context.prepare_store().save(
        (
            Step(project="zeta", verb=Verb.CLONE, path=".env"),
            Step(project="acme", verb=Verb.CLONE, path="node_modules"),
            Step(project="acme", verb=Verb.RUN, command="install-things", directory="web"),
        )
    )

    settings.run(context)

    rows = [told.text for told in ui.told if told.kind == "row"]
    paths = [row for row in rows if "acme/" in row or "zeta/" in row]
    assert [row.split(" | ")[0] for row in paths] == ["acme/node_modules", "zeta/.env"]
    assert not any("install-things" in row for row in paths), "a command is not a path"


def test_a_folder_whose_remembered_answers_disagree_stays_one_row(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """A folder used to be opened out into its own rows the moment its paths disagreed,
    because one checkbox could only lie about them. `◐` says *some of these*, so the
    folder keeps its row — and the answers under it keep themselves."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgP4a")
    ui = FakeUi(["preparation", [], "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )
    context.prepare_store().save(
        (
            Step(project="acme", verb=Verb.CLONE, path="web/.env"),
            Step(project="acme", verb=Verb.SKIP, path="web/a.log"),
            Step(project="acme", verb=Verb.SKIP, path="web/b.log"),
        )
    )

    settings.run(context)

    rows = [told.text for told in ui.told if told.kind == "row"]
    assert [row.split(" | ")[0] for row in rows if "acme/" in row] == [
        "acme/web/ · 3 ignored paths"
    ]
    answers = {s.path: s.verb for s in context.prepare_store().load().for_project("acme")}
    assert answers == {"web/.env": Verb.CLONE, "web/a.log": Verb.SKIP, "web/b.log": Verb.SKIP}, (
        "an untouched screen changes nothing, mix and all"
    )


def test_answering_a_mixed_folder_brings_every_path_under_it_in(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """One keystroke on a folder is the point of the folder. A mix goes *in* — the answer
    somebody reaching for a directory row is after — and the press after it takes the
    whole subtree out."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgP4b")
    ui = FakeUi(["preparation", ["acme/web/ · 3 ignored paths"], "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )
    context.prepare_store().save(
        (
            Step(project="acme", verb=Verb.CLONE, path="web/.env"),
            Step(project="acme", verb=Verb.SKIP, path="web/a.log"),
            Step(project="acme", verb=Verb.SKIP, path="web/b.log"),
        )
    )

    settings.run(context)

    assert {s.verb for s in context.prepare_store().load().for_project("acme")} == {Verb.CLONE}


def test_a_remembered_path_arrives_ticked_and_can_be_taken_back_out(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """The complaint this replaced: changing an answer used to be Enter, change, pick.
    It is now one keystroke on the row, from the same screen entering a lane shows."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgP4")
    ui = FakeUi(["preparation", ["acme/node_modules"], "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )
    context.prepare_store().save((Step(project="acme", verb=Verb.CLONE, path="node_modules"),))

    settings.run(context)

    assert [s.verb for s in context.prepare_store().load().for_project("acme")] == [Verb.SKIP]


def test_a_path_left_out_can_be_brought_back_in_from_settings(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgP5")
    ui = FakeUi(["preparation", ["acme/vendor"], "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )
    context.prepare_store().save((Step(project="acme", verb=Verb.SKIP, path="vendor"),))

    settings.run(context)

    assert [s.verb for s in context.prepare_store().load().for_project("acme")] == [Verb.CLONE]


def test_the_running_total_says_per_lane_where_there_is_no_lane_in_hand(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """Accepting here copies nothing — it answers for every lane in that project from now
    on. `coming in` would say something imminent that is not about to happen."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgP8")
    ui = FakeUi(["preparation", [], "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )
    context.prepare_store().save((Step(project="acme", verb=Verb.CLONE, path="node_modules"),))

    settings.run(context)

    said = [told.text for told in ui.told if told.kind == "summary"]
    assert said and said[-1].endswith("in each lane"), said


def test_backing_out_of_the_preparation_screen_changes_nothing(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgP6")
    ui = FakeUi(["preparation", FakeUi.ABANDON, "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )
    context.prepare_store().save((Step(project="acme", verb=Verb.CLONE, path="node_modules"),))

    settings.run(context)

    assert [s.verb for s in context.prepare_store().load().for_project("acme")] == [Verb.CLONE]


def test_with_no_paths_at_all_the_screen_says_so_rather_than_drawing_a_frame(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """§12: a screen built around a list does not render the list's frame when the list
    is empty — and a checklist has no action row to keep it alive, since every row it
    draws is a path."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgP7")
    ui = FakeUi(["preparation", "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )

    settings.run(context)

    assert ui.checklists == 0, "no checklist over nothing"
    assert ui.said("Nothing has been answered yet")


# -- settings · commands ----------------------------------------------------------


def test_settings_has_a_commands_row_and_lists_the_run_steps(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """A command is not a path: it is typed rather than discovered, and it has a
    directory and a guard to edit. So it keeps the list you act on a row of."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgC1")
    ui = FakeUi(["commands", "back", "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )
    context.prepare_store().save(
        (
            Step(project="acme", verb=Verb.CLONE, path="node_modules"),
            Step(project="acme", verb=Verb.RUN, command="install-things", directory="web"),
        )
    )

    settings.run(context)

    rows = [told.text for told in ui.told if told.kind == "row"]
    assert any("commands" in row and "1 step" in row for row in rows)
    assert any("acme/install-things" in row for row in rows)
    assert not any("node_modules" in row for row in rows), "a path is not a command"


def test_a_command_step_can_be_added(xdg: Path, projects_root: Path, lanes_root: Path) -> None:
    """`run` exists only here: the preparation screen is one row per discovered path, and
    a command is not a discovered path."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgC2")
    ui = FakeUi(
        [
            "commands",
            "add a command",
            "p",
            "install-things",
            "web",
            "web/node_modules",
            "back",
            "back",
        ]
    )
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )

    settings.run(context)

    step = context.prepare_store().load().for_project("p")[0]
    assert step.verb is Verb.RUN
    assert (step.command, step.directory, step.unless) == (
        "install-things",
        "web",
        "web/node_modules",
    )


def test_forgetting_a_command_leaves_the_paths_alone(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgC3")
    ui = FakeUi(["commands", "acme/install-things", "forget", "back", "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )
    context.prepare_store().save(
        (
            Step(project="acme", verb=Verb.CLONE, path="node_modules"),
            Step(project="acme", verb=Verb.RUN, command="install-things"),
        )
    )

    settings.run(context)

    assert [s.path for s in context.prepare_store().load().steps] == ["node_modules"]


def test_with_no_commands_at_all_the_screen_still_offers_add_a_command(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """§12 is about *data* rows: a screen whose only purpose is to let you add the first
    command cannot answer with a line of prose."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgC4")
    ui = FakeUi(["commands", "back", "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )

    settings.run(context)

    assert any("add a command" in told.text for told in ui.told if told.kind == "row")


def test_bringing_a_path_in_warns_when_copy_on_write_is_not_possible(
    xdg: Path, projects_root: Path, lanes_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Said where it changes a decision, in the same words doctor uses — doctor is not
    something a user consults before configuring something they expect to be free."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgC5")
    monkeypatch.setattr(apply, "cloning_available", _never)
    ui = FakeUi(["preparation", ["acme/vendor"], "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )
    context.prepare_store().save((Step(project="acme", verb=Verb.SKIP, path="vendor"),))

    settings.run(context)

    assert ui.said("copy-on-write")


# -- doctor on copy-on-write ------------------------------------------------------


def test_doctor_says_cloning_is_free_when_both_roots_share_a_volume(
    projects_root: Path, lanes_root: Path
) -> None:
    """The user configured 'clone' expecting it to be free. Doctor is where that
    expectation is checked before a gigabyte of disk quietly disappears."""
    lanes_root.mkdir()
    ui = FakeUi([])

    doctor.run(_context(ui, projects_root=projects_root, lanes_root=lanes_root))

    assert ui.said("copy-on-write")
    assert ui.said(str(projects_root))
    assert ui.said(str(lanes_root))


def test_doctor_says_cloning_is_a_real_copy_across_volumes(
    projects_root: Path, lanes_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(apply, "cloning_available", _never)
    ui = FakeUi([])

    doctor.run(_context(ui, projects_root=projects_root, lanes_root=lanes_root))

    assert ui.said("different volumes")
    assert ui.said("real disk")
    assert any(told.kind == "warn" and "Copy-on-write" in told.text for told in ui.told)


def test_doctor_still_renders_when_the_roots_are_unset(lanes_root: Path) -> None:
    ui = FakeUi([])
    doctor.run(_context(ui, projects_root=None, lanes_root=lanes_root))
    assert ui.said("Editor"), "it got all the way to the end"


def test_doctor_survives_a_probe_that_raises(
    projects_root: Path, lanes_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Doctor must render on a machine where nothing it inspects works, so the probe is a
    line rather than an exception."""

    def explode(source: Path, target: Path) -> bool:
        del source, target
        raise OSError("no")

    monkeypatch.setattr(apply, "cloning_available", explode)
    ui = FakeUi([])

    doctor.run(_context(ui, projects_root=projects_root, lanes_root=lanes_root))

    assert ui.said("could not be checked")
    assert ui.said("Editor")


def test_doctor_reports_an_unreadable_preparation_file(
    projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi([])
    context = _context(ui, projects_root=projects_root, lanes_root=lanes_root)
    store = context.prepare_store()
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("not toml [[[")

    doctor.run(context)

    assert ui.said("Could not read")
    assert ui.said(str(store.path))


def test_doctor_names_the_preparation_file_and_how_much_is_in_it(
    projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi([])
    context = _context(ui, projects_root=projects_root, lanes_root=lanes_root)
    context.prepare_store().save((Step(project="acme", verb=Verb.CLONE, path="node_modules"),))

    doctor.run(context)

    assert ui.said("prepare.toml")
    assert ui.said("1 step")


def _never(source: Path, target: Path) -> bool:
    """Stand in for a machine whose two roots are on different volumes."""
    del source, target
    return False


# -- settings · branch prefixes ----------------------------------------------------


def test_settings_has_a_branch_prefixes_row_listing_the_six_it_ships_with(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """A destination rather than a setting, so it is a noun (§4) — and with nothing
    customised it shows exactly what `open` has always offered."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgB1")
    ui = FakeUi(["branch prefixes", "back", "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )

    settings.run(context)

    rows = [told.text for told in ui.told if told.kind == "row"]
    assert any("branch prefixes" in row and "6 prefixes" in row for row in rows)
    for prefix in DEFAULT_PREFIXES:
        assert any(row.startswith(prefix) for row in rows), f"{prefix} is not on the screen"
    assert any("add a prefix" in row for row in rows), "the way to add the first one"


def test_a_prefix_can_be_added_and_is_written_to_the_file(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """The first write is the seed plus the new one: adding `spike` must not be a way
    to lose the six, and the file is what is offered from then on."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgB2")
    ui = FakeUi(["branch prefixes", "add a prefix", "spike", "back", "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )

    settings.run(context)

    assert context.prefix_store().path.exists(), "it round-trips through the file"
    assert BranchPrefixStore(config_dir).load() == (*DEFAULT_PREFIXES, "spike")
    assert ui.said("spike"), "§9: every action ends by saying what happened"


def test_a_prefix_is_validated_the_way_a_whole_branch_name_is(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """`_choose_branch` sanitizes what was typed and then lets git judge it. A prefix
    that cannot combine with a lane name into a ref git accepts is not worth storing —
    it would sit on the menu until somebody chose it and got the error there, which is
    the wrong screen to find out on.
    """
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgB3")
    ui = FakeUi(["branch prefixes", "add a prefix", "  şube fix!!  ", "back", "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )

    settings.run(context)

    assert BranchPrefixStore(config_dir).load() == (*DEFAULT_PREFIXES, "sube-fix")
    assert ui.said("sube-fix"), "and it says what it is actually storing"


def test_a_prefix_git_will_not_take_is_refused_rather_than_stored(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgB4")
    ui = FakeUi(["branch prefixes", "add a prefix", "///", "back", "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )

    settings.run(context)

    assert BranchPrefixStore(config_dir).load() == DEFAULT_PREFIXES
    assert any(told.kind == "error" for told in ui.told)


def test_changing_a_prefix_keeps_its_place_in_the_menu(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """Order is what the branch prompt shows, so a rename is a rename rather than a
    forget-and-add that would drop the row to the bottom."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgB5")
    BranchPrefixStore(config_dir).save(("feature", "bugfix", "chore"))
    ui = FakeUi(["branch prefixes", "bugfix", "change", "fix", "back", "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )

    settings.run(context)

    assert BranchPrefixStore(config_dir).load() == ("feature", "fix", "chore")


def test_forgetting_a_prefix_takes_it_off_the_menu_and_leaves_the_rest(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgB6")
    BranchPrefixStore(config_dir).save(("feature", "bugfix", "chore"))
    ui = FakeUi(["branch prefixes", "bugfix", "forget", "back", "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )

    settings.run(context)

    assert BranchPrefixStore(config_dir).load() == ("feature", "chore")
    assert ui.said("bugfix")


def test_forgetting_a_prefix_leaves_a_lane_already_on_it_exactly_as_it_was(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """The setting is the *menu*, not a naming policy applied to what already exists.

    A branch is a git ref that has been pushed, reviewed and built on; a prefix leaving
    the menu says nothing about it. There is deliberately nothing to renaming here — the
    two are not connected, and this is the test that keeps them unconnected.
    """
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgB7")
    build_repo(projects_root / "_build", default_branch="main")[1].rename(projects_root / "thing")

    opening = FakeUi(["thing", "new work", "Broken export", "branch", "hotfix/broken-export"])
    open_lane.run(
        _context(opening, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir)
    )

    forgetting = FakeUi(["branch prefixes", "hotfix", "forget", "back", "back"])
    settings.run(
        _context(
            forgetting, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
        )
    )

    lane_path = lanes_root / "thing" / "broken-export"
    assert CliGitBackend().status(lane_path, "main").branch == "hotfix/broken-export"
    assert [lane.name for lane in LaneStore(lanes_root).list_lanes()] == ["broken-export"]
    assert "hotfix" not in BranchPrefixStore(config_dir).load(), "gone from the menu, though"


def test_forgetting_the_last_prefix_says_the_six_are_back_rather_than_letting_them_reappear(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """A menu with nothing on it is not an answer anybody chose, so an empty list means
    the seed (`lane/prefixes.py`). The screen has to say so: six rows reappearing on the
    next repaint, unexplained, reads as the forget having failed."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgB8")
    BranchPrefixStore(config_dir).save(("spike",))
    ui = FakeUi(["branch prefixes", "spike", "forget", "back", "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )

    settings.run(context)

    assert BranchPrefixStore(config_dir).load() == DEFAULT_PREFIXES
    assert ui.said("the six")


def test_a_prefix_that_is_already_offered_is_not_added_a_second_time(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """Two identical rows are two identical entries at the branch prompt, where picking
    either does the same thing — a menu that has stopped being a choice."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgB9")
    ui = FakeUi(["branch prefixes", "add a prefix", "feature", "back", "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )

    settings.run(context)

    assert BranchPrefixStore(config_dir).load() == DEFAULT_PREFIXES
    assert ui.said("already")


def test_changing_a_prefix_to_a_name_already_on_the_menu_is_refused(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """The same rule as adding one, reached from the other door. Renaming `chore` to
    `feature` would merge two rows into one and silently drop `chore`."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgB10")
    BranchPrefixStore(config_dir).save(("feature", "chore"))
    ui = FakeUi(["branch prefixes", "chore", "change", "feature", "back", "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )

    settings.run(context)

    assert BranchPrefixStore(config_dir).load() == ("feature", "chore")
    assert ui.said("already")


def test_leaving_a_prefix_as_it_was_is_a_quiet_no_op(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """`change` offers the current name as the default, so pressing Enter on it is the
    commonest way to back out of a rename. Telling somebody their own prefix is `already
    offered` for accepting the default they were shown is an accusation, not a report."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgB11")
    BranchPrefixStore(config_dir).save(("feature", "chore"))
    ui = FakeUi(["branch prefixes", "chore", "change", "chore", "back", "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )

    settings.run(context)

    assert BranchPrefixStore(config_dir).load() == ("feature", "chore")
    assert not ui.said("already"), "accepting the default is not an attempt to duplicate"

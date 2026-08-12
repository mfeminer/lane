"""Doctor and settings.

The listing moved to `test_listing.py` when it became a screen of its own.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lane.actions import doctor, settings
from lane.config import Config, ConfigStore
from lane.context import Context
from lane.git.cli_backend import CliGitBackend
from lane.lanes import LaneStore
from lane.prepare import Step, Verb, apply
from lane.state import StateStore
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
        def text(self, title, *, default="", on_render=None):  # type: ignore[no-untyped-def]
            if "lanes be parked" in title:
                offered.append(default)
            return super().text(title, default=default, on_render=on_render)

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
        def text(self, title, *, default="", on_render=None):  # type: ignore[no-untyped-def]
            if "lanes be parked" in title:
                offered.append(default)
            return super().text(title, default=default, on_render=on_render)

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


def test_settings_has_a_preparation_row_saying_how_much_is_there(
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
    assert any("preparation" in row and "2 steps in 2 projects" in row for row in rows)


def test_the_preparation_screen_lists_every_projects_steps_with_the_project_dimmed(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """One screen for every project rather than a project list and then a page each: the
    lanes table already solves "rows from several projects in one table" with a dimmed
    lead, so this is two levels of nesting instead of three."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgP2")
    ui = FakeUi(["preparation", "back", "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )
    context.prepare_store().save(
        (
            Step(project="zeta", verb=Verb.LINK, path=".env"),
            Step(project="acme", verb=Verb.CLONE, path="node_modules", refresh=True),
            Step(project="acme", verb=Verb.RUN, command="install-things", directory="web"),
        )
    )

    settings.run(context)

    rows = [told.text for told in ui.told if told.kind == "row"]
    prepared = [row for row in rows if "acme/" in row or "zeta/" in row]
    assert [row.split(" | ")[0] for row in prepared] == [
        "acme/install-things",
        "acme/node_modules",
        "zeta/.env",
    ], "ordered by project, then subject, and never rearranging"
    assert any("clone, refreshed" in row for row in prepared)
    assert any("run · web" in row for row in prepared)
    assert any("add a step" in row for row in rows)


def test_changing_a_step_asks_one_question_and_returns_to_the_list(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgP3")
    ui = FakeUi(["preparation", "acme/node_modules", "change", "link", "back", "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )
    context.prepare_store().save((Step(project="acme", verb=Verb.CLONE, path="node_modules"),))

    settings.run(context)

    assert [s.verb for s in context.prepare_store().load().for_project("acme")] == [Verb.LINK]
    assert ui.unanswered() == 0, "the list came back, and 'back' answered it"


def test_a_clone_step_can_be_set_to_refresh_on_every_enter(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """The only place `refresh` can be set. On the screen where an answer is first given
    the path is absent, so `clone` and a refreshing `clone` do the same thing — a screen
    has no business offering a distinction it cannot demonstrate."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgP4")
    ui = FakeUi(["preparation", "acme/node_modules", "change", "clone, refreshed", "back", "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )
    context.prepare_store().save((Step(project="acme", verb=Verb.CLONE, path="node_modules"),))

    settings.run(context)

    step = context.prepare_store().load().for_project("acme")[0]
    assert step.verb is Verb.CLONE
    assert step.refresh


def test_forgetting_a_step_means_the_path_is_asked_about_again(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """The remedy the whole "every answer is remembered" decision rests on."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgP5")
    ui = FakeUi(["preparation", "acme/node_modules", "forget", "back", "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )
    context.prepare_store().save((Step(project="acme", verb=Verb.SKIP, path="node_modules"),))

    settings.run(context)

    assert context.prepare_store().load().steps == ()


def test_a_command_step_can_be_added(xdg: Path, projects_root: Path, lanes_root: Path) -> None:
    """`run` exists only here: the preparation screen is one row per discovered path, and
    a command is not a discovered path."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgP6")
    ui = FakeUi(
        [
            "preparation",
            "add a step",
            "p",
            "run",
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


def test_with_no_steps_at_all_the_screen_still_offers_add_a_step(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    """§12 is about *data* rows: a screen whose only purpose is to let you add the first
    step cannot answer with a line of prose."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgP7")
    ui = FakeUi(["preparation", "back", "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )

    settings.run(context)

    assert any("add a step" in told.text for told in ui.told if told.kind == "row")


def test_adding_a_clone_step_warns_when_copy_on_write_is_not_possible(
    xdg: Path, projects_root: Path, lanes_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Said where it changes a decision, in the same words doctor uses — doctor is not
    something a user consults before configuring something they expect to be free."""
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgP8")
    monkeypatch.setattr(apply, "cloning_available", _never)
    ui = FakeUi(["preparation", "add a step", "p", "clone", "vendor", "back", "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )

    settings.run(context)

    assert ui.said("copy-on-write")
    assert context.prepare_store().load().for_project("p")[0].verb is Verb.CLONE


def test_adding_a_link_step_says_the_lane_will_write_into_the_main_clone(
    xdg: Path, projects_root: Path, lanes_root: Path
) -> None:
    config_dir = _configured(xdg, projects_root, lanes_root, "cfgP9")
    ui = FakeUi(["preparation", "add a step", "p", "link", "vendor", "back", "back"])
    context = _context(
        ui, projects_root=projects_root, lanes_root=lanes_root, config_dir=config_dir
    )

    settings.run(context)

    assert ui.said("main clone")


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

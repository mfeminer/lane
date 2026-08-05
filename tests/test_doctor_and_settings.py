"""Doctor and settings.

The listing moved to `test_listing.py` when it became a screen of its own.
"""

from __future__ import annotations

from pathlib import Path

from lane.actions import doctor, settings
from lane.config import Config, ConfigStore
from lane.context import Context
from lane.git.cli_backend import CliGitBackend
from lane.lanes import LaneStore
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

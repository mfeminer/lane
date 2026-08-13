"""Opening a lane.

The structural claim under test: **everything is asked before anything is created**,
so abandoning at any prompt leaves nothing on disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lane.actions import open_lane
from lane.config import Config
from lane.context import Context
from lane.git.cli_backend import CliGitBackend
from lane.lanes import LaneStore
from lane.state import StateStore
from lane.ui.seam import Abandoned
from tests.conftest import Origin, build_repo, git
from tests.fakes import FakeEnvironment, FakeUi, StubGitHubClient


def make_context(
    ui: FakeUi,
    projects_root: Path,
    lanes_root: Path,
    *,
    environment: FakeEnvironment | None = None,
    editor: str = "cursor",
) -> Context:
    from lane.config import ConfigStore

    return Context(
        ui=ui,
        git=CliGitBackend(),
        github=StubGitHubClient(),
        environment=environment or FakeEnvironment(tools={"git": "/g", "cursor": "/c"}),
        config=Config(projects_root=projects_root, lanes_root=lanes_root, editor=editor),
        config_store=ConfigStore(lanes_root.parent / "config"),
        state_store=StateStore(lanes_root.parent / "state"),
    )


@pytest.fixture
def project(projects_root: Path) -> tuple[Origin, Path]:
    """A repository sitting directly under the projects root, as lane expects."""
    origin, clone = build_repo(projects_root / "_build", default_branch="main")
    target = projects_root / "thing"
    clone.rename(target)
    return origin, target


# -- I1: nothing is created until everything is answered -------------------------


def test_abandoning_the_project_prompt_creates_nothing(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi([FakeUi.ABANDON])
    context = make_context(ui, projects_root, lanes_root)

    with pytest.raises(Abandoned):
        open_lane.run(context)

    assert not lanes_root.exists()


@pytest.mark.parametrize("answers_before_abandon", [1, 2, 3])
def test_abandoning_any_later_prompt_creates_nothing(
    project: tuple[Origin, Path],
    projects_root: Path,
    lanes_root: Path,
    answers_before_abandon: int,
) -> None:
    """Project, description, mode, branch — abandoning any of them is a no-op."""
    script: list[object] = ["thing", "Fix the export", "branch", "feature/fix-the-export"]
    ui = FakeUi([*script[:answers_before_abandon], FakeUi.ABANDON])
    context = make_context(ui, projects_root, lanes_root)

    with pytest.raises(Abandoned):
        open_lane.run(context)

    assert LaneStore(lanes_root).list_lanes() == []


# -- I2, I3, I5, I7: the happy paths ---------------------------------------------


def test_opening_a_branch_lane_creates_a_worktree_with_no_upstream(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi(["thing", "Login sayfası hatası", "branch", "bugfix/login-sayfasi-hatasi"])
    environment = FakeEnvironment(tools={"git": "/g", "cursor": "/c"})
    context = make_context(ui, projects_root, lanes_root, environment=environment)

    open_lane.run(context)

    lane_path = lanes_root / "thing" / "login-sayfasi-hatasi"
    assert lane_path.is_dir()
    status = CliGitBackend().status(lane_path, "main")
    assert status.branch == "bugfix/login-sayfasi-hatasi"
    assert status.upstream is None, "the no-upstream invariant"
    # The editor was asked to open the lane, and only the lane.
    assert environment.launched == [("cursor", lane_path)]


def test_the_plan_is_shown_before_the_mode_is_asked(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi(["thing", "Fix export", "detached"])
    context = make_context(ui, projects_root, lanes_root)

    open_lane.run(context)

    assert ui.said("Starts at")
    assert ui.said("origin/main")
    assert ui.said("fix-export")


def test_branch_mode_offers_every_prefix_plus_bare_and_free_text(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    seen: list[str] = []

    class Recording(FakeUi):
        def choose(self, title, options, **kwargs):  # type: ignore[no-untyped-def]
            if title == "Branch name":
                seen.extend(o.label for o in options)
            return super().choose(title, options, **kwargs)

    ui = Recording(["thing", "Add audit log", "branch", "feature/add-audit-log"])
    open_lane.run(make_context(ui, projects_root, lanes_root))

    for prefix in ("feature", "bugfix", "hotfix", "chore", "refactor", "docs"):
        assert f"{prefix}/add-audit-log" in seen
    assert "add-audit-log" in seen, "the bare lane name"
    assert any("other" in label for label in seen), "a free-text option"


def test_detached_mode_sits_at_origin_base_with_no_branch(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    _, repo = project
    ui = FakeUi(["thing", "Have a look around", "detached"])
    context = make_context(ui, projects_root, lanes_root)

    open_lane.run(context)

    lane_path = lanes_root / "thing" / "have-a-look-around"
    status = CliGitBackend().status(lane_path, "main")
    assert status.detached
    assert status.branch is None
    assert (
        git(["rev-parse", "HEAD"], cwd=lane_path).strip()
        == git(["rev-parse", "origin/main"], cwd=repo).strip()
    )


def test_a_new_lane_starts_from_the_freshly_fetched_remote_tip(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    """A lane must start from `origin/<base>` as of the fetch it just did, not from
    whichever commit the local `main` branch happens to be sitting on — that local
    branch is exactly what can be days behind."""
    origin, repo = project
    local_main = git(["rev-parse", "main"], cwd=repo).strip()
    tip = origin.advance("a commit the local clone has not seen yet")
    assert tip != local_main, "the fixture must actually be behind for this to prove anything"

    ui = FakeUi(["thing", "Add audit log", "detached"])
    context = make_context(ui, projects_root, lanes_root)

    open_lane.run(context)

    lane_path = lanes_root / "thing" / "add-audit-log"
    assert git(["rev-parse", "HEAD"], cwd=lane_path).strip() == tip


def test_a_hand_typed_branch_name_is_sanitised(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi(["thing", "Deneme", "branch", "other…", "EMİN/deneme  şube!!"])
    context = make_context(ui, projects_root, lanes_root)

    open_lane.run(context)

    lane_path = lanes_root / "thing" / "deneme"
    assert CliGitBackend().status(lane_path, "main").branch == "EMIN/deneme-sube"


# -- I4: a rejected branch name re-asks rather than aborting ---------------------


def test_a_branch_name_git_rejects_is_re_asked(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi(
        [
            "thing",
            "Try again",
            "branch",
            "other…",
            "HEAD",  # git rejects this as a branch name
            "other…",
            "feature/second-try",
        ]
    )
    context = make_context(ui, projects_root, lanes_root)

    open_lane.run(context)

    lane_path = lanes_root / "thing" / "try-again"
    assert CliGitBackend().status(lane_path, "main").branch == "feature/second-try"
    assert ui.said("rejects")


# -- I6: an existing lane is refused before anything is created ------------------


def test_an_already_open_lane_is_refused(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi(["thing", "Same task", "detached"])
    context = make_context(ui, projects_root, lanes_root)
    open_lane.run(context)

    second = FakeUi(["thing", "Same task"])
    open_lane.run(make_context(second, projects_root, lanes_root))

    assert second.said("already open")


# -- descriptions that cannot become a name --------------------------------------


def test_a_description_that_yields_no_ascii_name_is_refused(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi(["thing", "日本語"])
    context = make_context(ui, projects_root, lanes_root)

    open_lane.run(context)

    assert ui.said("could not derive")
    assert LaneStore(lanes_root).list_lanes() == []


def test_an_empty_description_is_refused(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi(["thing", "   "])
    open_lane.run(make_context(ui, projects_root, lanes_root))

    assert ui.said("needs a description")


# -- I7: a missing editor is a warning, not a failure ---------------------------


def test_a_missing_editor_warns_and_names_the_path(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi(["thing", "No editor here", "detached"])
    environment = FakeEnvironment(tools={"git": "/g"})  # no editor on PATH
    context = make_context(ui, projects_root, lanes_root, environment=environment)

    open_lane.run(context)

    lane_path = lanes_root / "thing" / "no-editor-here"
    assert lane_path.is_dir(), "the lane still opens"
    assert ui.said("not on your PATH")
    assert ui.said(str(lane_path))


# -- I8: the last project is remembered -----------------------------------------


def test_the_last_project_used_is_offered_first(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    git(["init", "--quiet", str(projects_root / "aaa-earlier-alphabetically")])
    first = FakeUi(["thing", "First task", "detached"])
    context = make_context(first, projects_root, lanes_root)
    open_lane.run(context)

    offered: list[str] = []

    class Recording(FakeUi):
        def choose(self, title, options, **kwargs):  # type: ignore[no-untyped-def]
            if title.startswith("Which project"):
                offered.extend(o.label for o in options)
            return super().choose(title, options, **kwargs)

    second = Recording(["thing", "Second task", "detached"])
    open_lane.run(make_context(second, projects_root, lanes_root))

    assert offered[0] == "thing", f"last used should come first, got {offered}"


# -- metadata -------------------------------------------------------------------


def test_opening_a_lane_records_its_metadata_outside_the_worktree(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    _, repo = project
    ui = FakeUi(["thing", "Fix the exporter", "branch", "feature/fix-the-exporter"])
    context = make_context(ui, projects_root, lanes_root)

    open_lane.run(context)

    store = LaneStore(lanes_root)
    meta = store.read_meta("thing", "fix-the-exporter")
    assert meta.description == "Fix the exporter"
    assert meta.base == "main"
    assert meta.repo == str(repo)
    assert meta.created
    # And the worktree is still clean, which is the point of keeping it outside.
    assert (
        CliGitBackend().status(store.lane_path("thing", "fix-the-exporter"), "main").dirty_count
        == 0
    )


# -- no projects ----------------------------------------------------------------


def test_no_projects_explains_how_many_subfolders_were_examined(
    projects_root: Path, lanes_root: Path
) -> None:
    for name in ("one", "two"):
        (projects_root / name).mkdir()
    ui = FakeUi([])

    open_lane.run(make_context(ui, projects_root, lanes_root))

    assert ui.said("2 subfolder")
    assert ui.said("<project>/.git")


def test_nested_repositories_are_pointed_at(projects_root: Path, lanes_root: Path) -> None:
    org = projects_root / "acme"
    org.mkdir()
    git(["init", "--quiet", str(org / "Acme.Widgets")])
    ui = FakeUi([])

    open_lane.run(make_context(ui, projects_root, lanes_root))

    assert ui.said("nested")
    assert ui.said(str(org))


# -- opening ends by entering ----------------------------------------------------


def test_opening_a_lane_ends_by_entering_it(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    """One code path rather than two: `open` created the worktree, and everything that
    happens to a lane you are about to work in happens in `enter`. Before this, the
    editor launch and its missing-editor warning existed twice."""
    _origin, repo = project
    (repo / ".gitignore").write_text("node_modules/\n")
    git(["add", ".gitignore"], cwd=repo)
    git(["commit", "--quiet", "-m", "ignore"], cwd=repo)
    git(["push", "--quiet", "origin", "HEAD"], cwd=repo)
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "pkg").write_text("pkg\n")

    ui = FakeUi(
        [
            "thing",
            "Fix pagination",
            "branch",
            "bugfix/fix-pagination",
            ("space", "node_modules"),
            "continue",
        ]
    )
    context = make_context(ui, projects_root, lanes_root)

    open_lane.run(context)

    lane_path = lanes_root / "thing" / "fix-pagination"
    assert (lane_path / "node_modules" / "pkg").read_text() == "pkg\n", (
        "the new lane was prepared, not just created"
    )
    assert ui.said("Preparing thing/fix-pagination")


def test_opening_a_lane_in_a_project_with_nothing_ignored_asks_nothing_extra(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi(["thing", "Fix pagination", "branch", "bugfix/fix-pagination"])
    environment = FakeEnvironment(tools={"git": "/g", "cursor": "/c"})
    context = make_context(ui, projects_root, lanes_root, environment=environment)

    open_lane.run(context)

    assert ui.unanswered() == 0
    assert environment.launched, "and the editor still opened"
    assert not ui.said("Preparing")

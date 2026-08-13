"""Opening a lane.

The structural claim under test: **everything is asked before anything is created**,
so abandoning at any prompt leaves nothing on disk.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from lane.actions import open_lane
from lane.config import Config
from lane.context import Context
from lane.git.cli_backend import CliGitBackend
from lane.lanes import LaneStore
from lane.state import StateStore
from lane.ui.seam import Abandoned, Column, Row
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


@pytest.mark.parametrize("answers_before_abandon", [1, 2, 3, 4])
def test_abandoning_any_later_prompt_creates_nothing(
    project: tuple[Origin, Path],
    projects_root: Path,
    lanes_root: Path,
    answers_before_abandon: int,
) -> None:
    """Project, kind, description, mode, branch — abandoning any of them is a no-op."""
    script: list[object] = [
        "thing",
        "new work",
        "Fix the export",
        "branch",
        "feature/fix-the-export",
    ]
    ui = FakeUi([*script[:answers_before_abandon], FakeUi.ABANDON])
    context = make_context(ui, projects_root, lanes_root)

    with pytest.raises(Abandoned):
        open_lane.run(context)

    assert LaneStore(lanes_root).list_lanes() == []


# -- I2, I3, I5, I7: the happy paths ---------------------------------------------


def test_opening_a_branch_lane_creates_a_worktree_with_no_upstream(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi(
        ["thing", "new work", "Login sayfası hatası", "branch", "bugfix/login-sayfasi-hatasi"]
    )
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
    ui = FakeUi(["thing", "new work", "Fix export", "detached"])
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

    ui = Recording(["thing", "new work", "Add audit log", "branch", "feature/add-audit-log"])
    open_lane.run(make_context(ui, projects_root, lanes_root))

    for prefix in ("feature", "bugfix", "hotfix", "chore", "refactor", "docs"):
        assert f"{prefix}/add-audit-log" in seen
    assert "add-audit-log" in seen, "the bare lane name"
    assert any("other" in label for label in seen), "a free-text option"


def test_detached_mode_sits_at_origin_base_with_no_branch(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    _, repo = project
    ui = FakeUi(["thing", "new work", "Have a look around", "detached"])
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

    ui = FakeUi(["thing", "new work", "Add audit log", "detached"])
    context = make_context(ui, projects_root, lanes_root)

    open_lane.run(context)

    lane_path = lanes_root / "thing" / "add-audit-log"
    assert git(["rev-parse", "HEAD"], cwd=lane_path).strip() == tip


def test_a_hand_typed_branch_name_is_sanitised(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi(["thing", "new work", "Deneme", "branch", "other…", "EMİN/deneme  şube!!"])
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
            "new work",
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
    ui = FakeUi(["thing", "new work", "Same task", "detached"])
    context = make_context(ui, projects_root, lanes_root)
    open_lane.run(context)

    second = FakeUi(["thing", "new work", "Same task"])
    open_lane.run(make_context(second, projects_root, lanes_root))

    assert second.said("already open")


# -- descriptions that cannot become a name --------------------------------------


def test_a_description_that_yields_no_ascii_name_is_refused(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi(["thing", "new work", "日本語"])
    context = make_context(ui, projects_root, lanes_root)

    open_lane.run(context)

    assert ui.said("could not derive")
    assert LaneStore(lanes_root).list_lanes() == []


def test_an_empty_description_is_refused(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi(["thing", "new work", "   "])
    open_lane.run(make_context(ui, projects_root, lanes_root))

    assert ui.said("needs a description")


# -- I7: a missing editor is a warning, not a failure ---------------------------


def test_a_missing_editor_warns_and_names_the_path(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    ui = FakeUi(["thing", "new work", "No editor here", "detached"])
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
    first = FakeUi(["thing", "new work", "First task", "detached"])
    context = make_context(first, projects_root, lanes_root)
    open_lane.run(context)

    offered: list[str] = []

    class Recording(FakeUi):
        def choose(self, title, options, **kwargs):  # type: ignore[no-untyped-def]
            if title.startswith("Which project"):
                offered.extend(o.label for o in options)
            return super().choose(title, options, **kwargs)

    second = Recording(["thing", "new work", "Second task", "detached"])
    open_lane.run(make_context(second, projects_root, lanes_root))

    assert offered[0] == "thing", f"last used should come first, got {offered}"


# -- metadata -------------------------------------------------------------------


def test_opening_a_lane_records_its_metadata_outside_the_worktree(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    _, repo = project
    ui = FakeUi(["thing", "new work", "Fix the exporter", "branch", "feature/fix-the-exporter"])
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
            "new work",
            "Fix pagination",
            "branch",
            "bugfix/fix-pagination",
            ["node_modules"],
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
    ui = FakeUi(["thing", "new work", "Fix pagination", "branch", "bugfix/fix-pagination"])
    environment = FakeEnvironment(tools={"git": "/g", "cursor": "/c"})
    context = make_context(ui, projects_root, lanes_root, environment=environment)

    open_lane.run(context)

    assert ui.unanswered() == 0
    assert environment.launched, "and the editor still opened"
    assert not ui.said("Preparing")


# -- opening a lane on a branch that is already there ----------------------------
#
# Opening a lane is not always new work: picking up a branch a colleague pushed,
# coming back to something abandoned, reviewing a pull request locally. The choice
# is made properly, after the project, and then the two flows diverge.


def test_the_two_kinds_of_lane_are_offered_after_the_project(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    seen: list[str] = []

    class Recording(FakeUi):
        def choose(self, title, options, **kwargs):  # type: ignore[no-untyped-def]
            if title == open_lane.KIND_QUESTION:
                seen.extend(o.label for o in options)
            return super().choose(title, options, **kwargs)

    ui = Recording(["thing", "new work", "Fix export", "detached"])
    open_lane.run(make_context(ui, projects_root, lanes_root))

    assert seen == ["new work", "existing branch"]
    assert ui.asked[0].startswith("Which project"), "the project still comes first"
    assert ui.asked[1] == open_lane.KIND_QUESTION


def test_adopting_a_branch_that_only_exists_on_the_remote_tracks_it(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    """The colleague's-branch case, and the upstream half of it.

    A branch lane creates gets no upstream, because the only candidate would be
    `origin/<base>`. A branch adopted from origin tracks `origin/<itself>`: expected,
    what makes the unpushed count a real measurement, and unable to reach the default
    branch because it is not the default branch.
    """
    origin, repo = project
    origin.create_branch("feature/colleague-work")
    git(["fetch", "--quiet", "--prune", "origin"], cwd=repo)

    ui = FakeUi(["thing", "existing branch", "feature/colleague-work", ""])
    context = make_context(ui, projects_root, lanes_root)

    open_lane.run(context)

    lane_path = lanes_root / "thing" / "feature-colleague-work"
    status = CliGitBackend().status(lane_path, "main")
    assert status.branch == "feature/colleague-work"
    assert status.upstream == "origin/feature/colleague-work"


def test_the_first_push_hint_is_only_given_where_lane_withheld_the_upstream(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    """lane prints that hint to explain a decision it made.

    It withholds the upstream on a branch it creates, so the absence would otherwise
    read as a bug. It withholds nothing from a branch it adopted — that one already
    tracks `origin/<itself>`, so `git push -u` is advice for a situation the user is
    not in, and where a local branch genuinely has no upstream git's own message says
    so far better than lane guessing.
    """
    origin, repo = project
    origin.create_branch("feature/already-on-origin")
    git(["fetch", "--quiet", "--prune", "origin"], cwd=repo)

    created = FakeUi(["thing", "new work", "Brand new", "branch", "feature/brand-new"])
    open_lane.run(make_context(created, projects_root, lanes_root))
    assert created.said("git push -u origin feature/brand-new")

    adopted = FakeUi(["thing", "existing branch", "feature/already-on-origin", ""])
    open_lane.run(make_context(adopted, projects_root, lanes_root))
    assert not adopted.said("push -u"), "the branch already has an upstream"


def test_adopting_a_local_branch_leaves_its_upstream_alone(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    _, repo = project
    # `--no-track`, so the branch genuinely has no upstream for lane to leave alone:
    # `git branch <name> origin/<x>` sets one by itself.
    git(["branch", "--no-track", "chore/local-only", "origin/main"], cwd=repo)

    ui = FakeUi(["thing", "existing branch", "chore/local-only", ""])
    open_lane.run(make_context(ui, projects_root, lanes_root))

    lane_path = lanes_root / "thing" / "chore-local-only"
    status = CliGitBackend().status(lane_path, "main")
    assert status.branch == "chore/local-only"
    assert status.upstream is None, "lane must not invent an upstream for a local branch"


def test_the_existing_branch_path_fetches_with_prune_before_it_lists_anything(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    """Otherwise it offers branches deleted on the remote weeks ago."""
    origin, _repo = project
    origin.create_branch("feature/still-there")
    listed: list[str] = []

    class Recording(FakeUi):
        def browse(self, title, columns, rows, **kwargs):  # type: ignore[no-untyped-def]
            listed.extend(row.cells[0].text for row in rows())
            return super().browse(title, columns, rows, **kwargs)

    ui = Recording(["thing", "existing branch", "feature/still-there", ""])
    open_lane.run(make_context(ui, projects_root, lanes_root))

    assert "feature/still-there" in listed, "a branch pushed since the clone must appear"
    fetching = [told.text for told in ui.told if told.kind == "progress"]
    assert any("Fetching" in text for text in fetching)


def test_a_branch_checked_out_in_the_main_clone_is_shown_and_refused(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    """Prerequisites are enforced where they are used, never by hiding an entry.

    The default branch is always checked out in the main clone, so this is the case
    every user meets first — and a row that simply is not there cannot explain itself.
    """
    _, repo = project
    listed: list[str] = []

    class Recording(FakeUi):
        def browse(self, title, columns, rows, **kwargs):  # type: ignore[no-untyped-def]
            listed.extend(row.cells[0].text for row in rows())
            return super().browse(title, columns, rows, **kwargs)

    ui = Recording(["thing", "existing branch", "main", "back"])
    with pytest.raises(Abandoned):
        open_lane.run(make_context(ui, projects_root, lanes_root))

    assert "main" in listed, "the unavailable branch is shown, not hidden"
    assert ui.said("main clone")
    assert ui.said(str(repo))
    assert LaneStore(lanes_root).list_lanes() == []


def test_a_branch_held_by_a_worktree_that_is_not_a_lane_names_the_path(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path, tmp_path: Path
) -> None:
    """Not every worktree is lane's. A user can make one by hand, and a removed lane
    leaves a stale entry until something prunes it — neither is the main clone, and
    saying so would send the user to look in the wrong place."""
    _, repo = project
    by_hand = tmp_path / "by-hand"
    git(["worktree", "add", "--quiet", "-b", "feature/by-hand", str(by_hand)], cwd=repo)
    drawn: dict[str, str] = {}

    class Recording(FakeUi):
        def browse(self, title, columns, rows, **kwargs):  # type: ignore[no-untyped-def]
            for row in rows():
                drawn[row.cells[0].text] = row.cells[1].text
            return super().browse(title, columns, rows, **kwargs)

    ui = Recording(["thing", "existing branch", "feature/by-hand", "back"])
    with pytest.raises(Abandoned):
        open_lane.run(make_context(ui, projects_root, lanes_root))

    assert drawn["feature/by-hand"] == "in another worktree"
    assert drawn["main"] == "in the main clone", "and the main clone is still named as one"
    assert ui.said(str(by_hand)), "the refusal points at where it actually is"


def test_a_branch_held_by_another_lane_names_that_lane_and_offers_to_enter_it(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    """lane knows which lane has it, which is a better answer than an error."""
    first = FakeUi(["thing", "new work", "Fix export", "branch", "feature/fix-export"])
    open_lane.run(make_context(first, projects_root, lanes_root))

    environment = FakeEnvironment(tools={"git": "/g", "cursor": "/c"})
    second = FakeUi(["thing", "existing branch", "feature/fix-export", True])
    context = make_context(second, projects_root, lanes_root, environment=environment)

    open_lane.run(context)

    assert second.said("thing/fix-export"), "the refusal names the lane holding it"
    assert environment.launched == [("cursor", lanes_root / "thing" / "fix-export")]
    assert len(LaneStore(lanes_root).list_lanes()) == 1, "no second lane was created"


def test_declining_the_offer_returns_to_the_branch_list(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    """A refusal does not leave the screen: it is one the user is standing in."""
    first = FakeUi(["thing", "new work", "Fix export", "branch", "feature/fix-export"])
    open_lane.run(make_context(first, projects_root, lanes_root))
    origin, _repo = project
    origin.create_branch("feature/free")

    second = FakeUi(["thing", "existing branch", "feature/fix-export", False, "feature/free", ""])
    open_lane.run(make_context(second, projects_root, lanes_root))

    assert (lanes_root / "thing" / "feature-free").is_dir()


def test_the_lane_name_is_derived_from_the_branch_and_offered_for_editing(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    """The branch was named by somebody else for another purpose, so the forty
    character cap cuts it in a place nobody chose — and the name is a directory the
    user is about to live in."""
    origin, repo = project
    origin.create_branch("bugfix/a-long-branch-name-nobody-chose-for-this-lane")
    git(["fetch", "--quiet", "--prune", "origin"], cwd=repo)
    offered: list[str] = []

    class Recording(FakeUi):
        def text(self, title, *, default="", **kwargs):  # type: ignore[no-untyped-def]
            if title == open_lane.NAME_QUESTION:
                offered.append(default)
            return super().text(title, default=default, **kwargs)

    ui = Recording(
        [
            "thing",
            "existing branch",
            "bugfix/a-long-branch-name-nobody-chose-for-this-lane",
            "shorter-name",
        ]
    )
    open_lane.run(make_context(ui, projects_root, lanes_root))

    assert offered == ["bugfix-a-long-branch-name-nobody-chose-f"], "the slug, capped at 40"
    assert (lanes_root / "thing" / "shorter-name").is_dir()
    meta = LaneStore(lanes_root).read_meta("thing", "shorter-name")
    assert meta.description == "bugfix/a-long-branch-name-nobody-chose-for-this-lane"


def test_a_branch_slugging_to_an_open_lanes_name_re_asks_rather_than_aborting(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    """Unlike a description, a branch name cannot be reworded — so refusing outright
    would strand the user with no way to finish."""
    origin, repo = project
    origin.create_branch("feature/taken-name")
    git(["fetch", "--quiet", "--prune", "origin"], cwd=repo)
    first = FakeUi(["thing", "new work", "feature taken name", "detached"])
    open_lane.run(make_context(first, projects_root, lanes_root))
    assert (lanes_root / "thing" / "feature-taken-name").is_dir()

    second = FakeUi(["thing", "existing branch", "feature/taken-name", "", "second-look"])
    open_lane.run(make_context(second, projects_root, lanes_root))

    assert second.said("already open")
    assert (lanes_root / "thing" / "second-look").is_dir()


def test_detached_is_not_offered_when_picking_up_an_existing_branch(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    """An existing branch is the opposite of detached."""
    origin, repo = project
    origin.create_branch("feature/whatever")
    git(["fetch", "--quiet", "--prune", "origin"], cwd=repo)
    titles: list[str] = []
    offered: list[str] = []

    class Recording(FakeUi):
        def choose(self, title, options, **kwargs):  # type: ignore[no-untyped-def]
            titles.append(title)
            offered.extend(option.label for option in options)
            return super().choose(title, options, **kwargs)

    ui = Recording(["thing", "existing branch", "feature/whatever", ""])
    open_lane.run(make_context(ui, projects_root, lanes_root))

    assert not any("How should this lane start" in title for title in titles)
    assert "detached" not in offered, f"detached must not be offered here: {offered}"


def test_the_starting_commit_of_an_adopted_branch_is_where_it_left_the_base(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    """The commit from which everything on HEAD is this branch's own work.

    Recording the branch tip instead would make the listing say `no commits yet`
    about a branch full of unmerged work, and make the close flow file "no commits
    of its own — nothing to merge" as a clean note directly above the confirmation
    that deletes them.
    """
    origin, repo = project
    base = git(["rev-parse", "origin/main"], cwd=repo).strip()
    origin.create_branch("feature/already-busy")
    origin.advance("somebody else's work", branch="feature/already-busy")
    git(["fetch", "--quiet", "--prune", "origin"], cwd=repo)

    ui = FakeUi(["thing", "existing branch", "feature/already-busy", ""])
    open_lane.run(make_context(ui, projects_root, lanes_root))

    meta = LaneStore(lanes_root).read_meta("thing", "feature-already-busy")
    assert meta.start == base, "the merge base, not the branch tip"

    lane_path = lanes_root / "thing" / "feature-already-busy"
    status = CliGitBackend().status(lane_path, "main", meta.start)
    assert status.has_own_commits, "the branch's commits are not nothing"
    assert not status.merged


def test_the_starting_commit_of_a_new_branch_is_unchanged(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    """One rule covers both, because for a branch created at `origin/<base>` the
    merge base with the base *is* the head commit."""
    ui = FakeUi(["thing", "new work", "Fresh start", "branch", "feature/fresh-start"])
    open_lane.run(make_context(ui, projects_root, lanes_root))

    meta = LaneStore(lanes_root).read_meta("thing", "fresh-start")
    lane_path = lanes_root / "thing" / "fresh-start"
    assert meta.start == git(["rev-parse", "HEAD"], cwd=lane_path).strip()


def test_the_branch_list_says_where_each_branch_lives(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    """Colour never carries meaning alone: every state cell restates itself in words."""
    origin, repo = project
    origin.create_branch("feature/remote-side")
    git(["branch", "chore/mine", "origin/main"], cwd=repo)
    git(["fetch", "--quiet", "--prune", "origin"], cwd=repo)
    drawn: dict[str, str] = {}

    class Recording(FakeUi):
        def browse(self, title, columns, rows, **kwargs):  # type: ignore[no-untyped-def]
            for row in rows():
                drawn[row.cells[0].text] = row.cells[1].text
            return super().browse(title, columns, rows, **kwargs)

    ui = Recording(["thing", "existing branch", "chore/mine", ""])
    open_lane.run(make_context(ui, projects_root, lanes_root))

    assert drawn["feature/remote-side"] == "origin only"
    assert drawn["main"] == "in the main clone"
    assert drawn["chore/mine"] == "", "a branch you can simply take says nothing"


def test_the_branch_table_survives_a_narrow_terminal(
    project: tuple[Origin, Path], projects_root: Path, lanes_root: Path
) -> None:
    """`state` answers the screen's own question, so it is never dropped or
    truncated — the lanes table's rule, stated generally in the conventions."""
    from lane.ui.table import paint

    origin, repo = project
    origin.create_branch("feature/a-fairly-long-branch-name-here")
    git(["fetch", "--quiet", "--prune", "origin"], cwd=repo)
    captured: list[tuple[str, Sequence[Column], list[Row[object]]]] = []

    class Recording(FakeUi):
        def browse(self, title, columns, rows, **kwargs):  # type: ignore[no-untyped-def]
            captured.append((title, columns, list(rows())))
            return super().browse(title, columns, rows, **kwargs)

    ui = Recording(["thing", "existing branch", "main", "back"])
    with pytest.raises(Abandoned):
        open_lane.run(make_context(ui, projects_root, lanes_root))

    title, columns, rows = captured[0]
    painted = paint(title, columns, rows, "← Back", cursor=0, top=0, width=40, height=24)
    body = "\n".join(painted.lines)
    assert "main clone" in body, "the state column survives at 40 columns"
    for line in painted.lines:
        assert len(line) <= 40, f"{line!r} overflows a 40-column terminal"

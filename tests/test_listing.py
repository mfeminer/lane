"""The lane listing: one screen, with the cursor on the thing you are about to act on.

See ADR 0002. What is being asserted here is the *action* — which rows it builds,
what each cell says, what the panel adds, and where you end up after each verb. The
widget that draws it has its own tests in `test_table.py`, and never appears here:
these go through the seam, which the fake replaces whole.
"""

from __future__ import annotations

from pathlib import Path

from lane.actions import list_lanes
from lane.config import Config, ConfigStore
from lane.context import Context
from lane.git.cli_backend import CliGitBackend
from lane.github.client import CannotTell, NotApplicable, PullRequest, found
from lane.lanes import LaneMeta, LaneStore
from lane.state import StateStore
from tests.conftest import build_repo, git
from tests.fakes import FakeEnvironment, FakeUi, StubGitHubClient


def _context(
    ui: FakeUi,
    *,
    projects_root: Path,
    lanes_root: Path,
    environment: FakeEnvironment | None = None,
    github: StubGitHubClient | None = None,
) -> Context:
    return Context(
        ui=ui,
        git=CliGitBackend(),
        github=github or StubGitHubClient(),
        environment=environment or FakeEnvironment(tools={"git": "/g", "cursor": "/c"}),
        config=Config(projects_root=projects_root, lanes_root=lanes_root, editor="cursor"),
        config_store=ConfigStore(lanes_root.parent / "cfg"),
        state_store=StateStore(lanes_root.parent / "st"),
    )


def _two_lanes(projects_root: Path, lanes_root: Path) -> tuple[Path, LaneStore]:
    _origin, clone = build_repo(projects_root / "_b")
    repo = projects_root / "thing"
    clone.rename(repo)
    backend = CliGitBackend()
    store = LaneStore(lanes_root)

    clean = store.lane_path("thing", "clean-lane")
    backend.add_worktree_new_branch(repo, clean, "chore/clean-lane", "origin/main")
    store.write_meta(
        "thing",
        "clean-lane",
        LaneMeta(
            description="clean lane",
            base="main",
            repo=str(repo),
            created=LaneStore.timestamp(),
        ),
    )

    busy = store.lane_path("thing", "busy-lane")
    backend.add_worktree_new_branch(repo, busy, "feature/busy-lane", "origin/main")
    (busy / "wip.txt").write_text("in progress\n")
    git(["add", "-A"], cwd=busy)
    git(["commit", "--quiet", "-m", "wip"], cwd=busy)
    (busy / "more.txt").write_text("also in progress\n")
    store.write_meta(
        "thing",
        "busy-lane",
        LaneMeta(
            description="busy lane", base="main", repo=str(repo), created=LaneStore.timestamp()
        ),
    )
    return repo, store


# -- nothing to list ---------------------------------------------------------------


def test_no_lanes_says_so_and_draws_no_table(projects_root: Path, lanes_root: Path) -> None:
    """An empty table with headers is a worse answer than a sentence."""
    ui = FakeUi([])

    list_lanes.run(_context(ui, projects_root=projects_root, lanes_root=lanes_root))

    assert ui.said("No open lanes")
    assert not any(told.kind == "table" for told in ui.told)
    assert ui.asked == [], "and it asked nothing"


# -- what the rows say -------------------------------------------------------------


def test_the_rows_carry_the_lane_its_state_and_its_age(
    projects_root: Path, lanes_root: Path
) -> None:
    _two_lanes(projects_root, lanes_root)
    ui = FakeUi(["back"])

    list_lanes.run(_context(ui, projects_root=projects_root, lanes_root=lanes_root))

    transcript = ui.transcript
    assert "busy-lane" in transcript
    assert "● 1 uncommitted" in transcript
    assert "↑ 1 unpushed" in transcript
    # The clean lane was only just created, so it has done no work yet.
    assert "no commits yet" in transcript
    assert "today" in transcript


def test_the_project_moves_into_the_title_when_every_lane_shares_one(
    projects_root: Path, lanes_root: Path
) -> None:
    """`thing/` down every row is thirteen columns of the same string."""
    _two_lanes(projects_root, lanes_root)
    ui = FakeUi(["back"])

    list_lanes.run(_context(ui, projects_root=projects_root, lanes_root=lanes_root))

    title = next(told.text for told in ui.told if told.kind == "table")
    assert title == "2 open lanes in thing"
    rows = [told.text for told in ui.told if told.kind == "row"]
    assert not any(row.startswith("thing/") for row in rows)


def test_the_project_stays_on_the_row_when_lanes_span_projects(
    projects_root: Path, lanes_root: Path
) -> None:
    _two_lanes(projects_root, lanes_root)
    _origin, clone = build_repo(projects_root / "_c")
    other = projects_root / "other"
    clone.rename(other)
    store = LaneStore(lanes_root)
    CliGitBackend().add_worktree_new_branch(
        other, store.lane_path("other", "elsewhere"), "chore/elsewhere", "origin/main"
    )

    ui = FakeUi(["back"])
    list_lanes.run(_context(ui, projects_root=projects_root, lanes_root=lanes_root))

    title = next(told.text for told in ui.told if told.kind == "table")
    assert title == "3 open lanes", "there is no single project to name"
    rows = [told.text for told in ui.told if told.kind == "row"]
    assert any(row.startswith("other/elsewhere") for row in rows)
    assert any(row.startswith("thing/busy-lane") for row in rows)


def test_a_freshly_opened_lane_does_not_claim_to_be_merged(
    projects_root: Path, lanes_root: Path
) -> None:
    """It sits exactly at origin/<base>, so an ancestry check calls it merged —
    vacuously. There was never anything to merge."""
    _origin, clone = build_repo(projects_root / "_b")
    repo = projects_root / "thing"
    clone.rename(repo)
    store = LaneStore(lanes_root)
    CliGitBackend().add_worktree_new_branch(
        repo, store.lane_path("thing", "brand-new"), "chore/brand-new", "origin/main"
    )
    store.write_meta(
        "thing", "brand-new", LaneMeta(description="just opened", base="main", repo=str(repo))
    )

    ui = FakeUi(["back"])
    list_lanes.run(_context(ui, projects_root=projects_root, lanes_root=lanes_root))

    assert "merged" not in ui.transcript, ui.transcript
    assert "no commits yet" in ui.transcript


def test_a_lane_whose_work_reached_the_base_is_shown_as_merged(
    projects_root: Path, lanes_root: Path
) -> None:
    _origin, clone = build_repo(projects_root / "_b")
    repo = projects_root / "thing"
    clone.rename(repo)
    backend = CliGitBackend()
    store = LaneStore(lanes_root)
    lane = store.lane_path("thing", "landed")
    backend.add_worktree_new_branch(repo, lane, "feature/landed", "origin/main")
    started_at = backend.head_commit(lane)
    (lane / "work.txt").write_text("real work\n")
    git(["add", "-A"], cwd=lane)
    git(["commit", "--quiet", "-m", "real work"], cwd=lane)
    git(["push", "--quiet", "origin", "feature/landed:main"], cwd=lane)
    backend.fetch_prune(repo)
    store.write_meta(
        "thing",
        "landed",
        LaneMeta(description="landed", base="main", repo=str(repo), start=started_at),
    )

    ui = FakeUi(["back"])
    list_lanes.run(_context(ui, projects_root=projects_root, lanes_root=lanes_root))

    assert "✓ merged" in ui.transcript


def test_a_squash_merged_lane_is_not_called_unmerged_next_to_a_merged_pull_request(
    projects_root: Path, lanes_root: Path
) -> None:
    """The false negative the close flow already resolves, in the column that shows it.

    A squash merge lands the lane's work as one *new* commit, so none of the lane's
    own commits is an ancestor of `origin/<base>` and the ancestry check says "not
    merged yet" — while `pr` says `merged` one column over, about the same lane. The
    two cells contradicted each other on screen. A `MERGED` pull request settles it,
    exactly as it already does when closing: the work landed, however it landed.
    """
    _origin, clone = build_repo(projects_root / "_b")
    repo = projects_root / "thing"
    clone.rename(repo)
    backend = CliGitBackend()
    store = LaneStore(lanes_root)
    lane = store.lane_path("thing", "squashed")
    backend.add_worktree_new_branch(repo, lane, "feature/squashed", "origin/main")
    started_at = backend.head_commit(lane)
    (lane / "work.txt").write_text("real work\n")
    git(["add", "-A"], cwd=lane)
    git(["commit", "--quiet", "-m", "real work"], cwd=lane)
    # Pushed, as any lane with a pull request is: nothing is left unpushed, which is
    # what leaves `state` saying only "not merged yet".
    git(["push", "--quiet", "--set-upstream", "origin", "feature/squashed"], cwd=lane)
    store.write_meta(
        "thing",
        "squashed",
        LaneMeta(description="squashed", base="main", repo=str(repo), start=started_at),
    )

    # The squash, as GitHub performs it: the same content as one new commit on the
    # base, so the lane's own commit is nowhere in `origin/main`'s ancestry.
    (repo / "work.txt").write_text("real work\n")
    git(["add", "-A"], cwd=repo)
    git(["commit", "--quiet", "-m", "real work (#1012)"], cwd=repo)
    git(["push", "--quiet", "origin", "main"], cwd=repo)
    backend.fetch_prune(repo)

    premise = backend.status(lane, "main", started_at)
    assert not premise.merged, "the premise: git cannot see this work in the base"
    assert premise.has_own_commits and not premise.unpushed_count

    ui = FakeUi(["back"])
    list_lanes.run(
        _context(
            ui,
            projects_root=projects_root,
            lanes_root=lanes_root,
            github=StubGitHubClient(
                found(PullRequest(number=1012, state="MERGED", url="http://x/1012"))
            ),
        )
    )

    rows = " ".join(told.text for told in ui.told if told.kind == "row")
    assert "#1012 merged" in rows, "the pull request column was already right"
    assert "not merged yet" not in rows, "and state must not contradict it"
    assert "✓ merged" in rows


def test_a_lane_whose_remote_branch_was_deleted_is_not_also_called_unpushed(
    projects_root: Path, lanes_root: Path
) -> None:
    """`↑ 1 unpushed · ✓ merged`, about the same lane, in the same cell.

    Merging with *delete branch* removes `origin/<branch>`, so there is no remote left
    to measure against and the unpushed count falls back to `origin/main` — where the
    squash left none of the lane's commits. It is then counting work that landed, and
    printing it as a blocker beside `✓ merged` is the same contradiction `state` was
    already taught to avoid, reached from the other side.
    """
    origin, clone = build_repo(projects_root / "_b")
    repo = projects_root / "thing"
    clone.rename(repo)
    backend = CliGitBackend()
    store = LaneStore(lanes_root)
    lane = store.lane_path("thing", "squashed")
    backend.add_worktree_new_branch(repo, lane, "feature/squashed", "origin/main")
    started_at = backend.head_commit(lane)
    (lane / "work.txt").write_text("real work\n")
    git(["add", "-A"], cwd=lane)
    git(["commit", "--quiet", "-m", "real work"], cwd=lane)
    landed = git(["rev-parse", "HEAD"], cwd=lane).strip()
    git(["push", "--quiet", "--set-upstream", "origin", "feature/squashed"], cwd=lane)
    store.write_meta(
        "thing",
        "squashed",
        LaneMeta(description="squashed", base="main", repo=str(repo), start=started_at),
    )

    # The squash, and then the branch deletion that comes with it.
    (repo / "work.txt").write_text("real work\n")
    git(["add", "-A"], cwd=repo)
    git(["commit", "--quiet", "-m", "real work (#1012)"], cwd=repo)
    git(["push", "--quiet", "origin", "main"], cwd=repo)
    origin.delete_branch("feature/squashed")
    backend.fetch_prune(repo)

    premise = backend.status(lane, "main", started_at)
    assert premise.upstream is None, "the remote-tracking ref went with the merge"
    assert premise.unpushed_count == 1, "and the count fell back to origin/main"

    ui = FakeUi(["back"])
    list_lanes.run(
        _context(
            ui,
            projects_root=projects_root,
            lanes_root=lanes_root,
            github=StubGitHubClient(
                found(
                    PullRequest(number=1012, state="MERGED", url="http://x/1012", head_oid=landed)
                )
            ),
        )
    )

    rows = " ".join(told.text for told in ui.told if told.kind == "row")
    assert "✓ merged" in rows
    assert "unpushed" not in rows, "that count is measuring commits that landed"


def test_a_detached_lane_says_so_where_it_changes_what_closing_does(
    projects_root: Path, lanes_root: Path
) -> None:
    """The branch column is gone, so detachment has to live in `state`."""
    _origin, clone = build_repo(projects_root / "_b")
    repo = projects_root / "thing"
    clone.rename(repo)
    store = LaneStore(lanes_root)
    CliGitBackend().add_worktree_detached(repo, store.lane_path("thing", "loose"), "origin/main")
    store.write_meta("thing", "loose", LaneMeta(description="loose", base="main", repo=str(repo)))

    ui = FakeUi(["back"])
    list_lanes.run(_context(ui, projects_root=projects_root, lanes_root=lanes_root))

    assert "detached" in ui.transcript


# -- the pull request column -------------------------------------------------------


def test_pull_request_state_appears_in_its_own_column(
    projects_root: Path, lanes_root: Path
) -> None:
    _two_lanes(projects_root, lanes_root)
    pr = found(PullRequest(number=418, state="OPEN", url="https://github.com/a/b/pull/418"))
    ui = FakeUi(["back"])

    list_lanes.run(
        _context(
            ui,
            projects_root=projects_root,
            lanes_root=lanes_root,
            github=StubGitHubClient(pr),
        )
    )

    assert "#418 open" in ui.transcript
    assert "https://github.com/a/b/pull/418" in ui.transcript, "the panel carries the URL"


def test_the_column_shows_the_decisive_pull_request_and_the_panel_keeps_the_rest(
    projects_root: Path, lanes_root: Path
) -> None:
    """The column answers *can I close this*; the panel carries the history.

    One sentence, not a line each: the panel is capped at three lines and already
    spends them on the description, the branch and the pull request, so a line per
    pull request would be sliced off — dropping exactly the history this keeps.
    """
    _two_lanes(projects_root, lanes_root)
    history = found(
        PullRequest(number=41, state="MERGED", url="http://x/41"),
        PullRequest(number=42, state="OPEN", url="http://x/42"),
    )
    ui = FakeUi(["back"])

    list_lanes.run(
        _context(
            ui,
            projects_root=projects_root,
            lanes_root=lanes_root,
            github=StubGitHubClient(history),
        )
    )

    rows = " ".join(told.text for told in ui.told if told.kind == "row")
    panel = " ".join(told.text for told in ui.told if told.kind == "panel")
    assert "#42 open" in rows, "the open one is what holds the lane open"
    assert "#41" not in rows, "and the column stays one cell wide"
    assert "#41 merged" in panel, "the history is not dropped"
    assert "http://x/42" in panel, "the decisive one keeps its URL"
    panel_lines = [told for told in ui.told if told.kind == "panel"]
    assert len(panel_lines) <= 3 * 2, "two lanes, and the panel keeps at most three lines each"


def test_gh_being_unavailable_is_unknown_and_the_panel_says_how_to_fix_it(
    projects_root: Path, lanes_root: Path
) -> None:
    """`unknown` and `none` are different answers, and only one has a remedy."""
    _two_lanes(projects_root, lanes_root)
    cannot = CannotTell(reason="gh-missing", remedy="brew install gh", detail="gh is not installed")
    ui = FakeUi(["back"])

    list_lanes.run(
        _context(
            ui,
            projects_root=projects_root,
            lanes_root=lanes_root,
            github=StubGitHubClient(cannot),
        )
    )

    rows = " ".join(told.text for told in ui.told if told.kind == "row")
    assert "unknown" in rows
    assert "none" not in rows
    assert ui.said("brew install gh")
    assert "busy-lane" in ui.transcript, "the rest of the listing still rendered"


def test_no_pull_request_is_none_rather_than_unknown(projects_root: Path, lanes_root: Path) -> None:
    _two_lanes(projects_root, lanes_root)
    ui = FakeUi(["back"])

    list_lanes.run(
        _context(
            ui,
            projects_root=projects_root,
            lanes_root=lanes_root,
            github=StubGitHubClient(NotApplicable("not-github")),
        )
    )

    rows = " ".join(told.text for told in ui.told if told.kind == "row")
    assert "unknown" not in rows


def test_a_github_client_that_raises_still_renders_the_listing(
    projects_root: Path, lanes_root: Path
) -> None:
    _two_lanes(projects_root, lanes_root)

    class Exploding(StubGitHubClient):
        def pull_request_for(self, *, branch, remote_url, cwd):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    ui = FakeUi(["back"])
    list_lanes.run(
        _context(ui, projects_root=projects_root, lanes_root=lanes_root, github=Exploding())
    )

    assert "unknown" in ui.transcript
    assert "busy-lane" in ui.transcript


# -- the slow column does not hold up the first paint ------------------------------


def test_the_table_is_complete_before_any_gh_call_is_made(
    projects_root: Path, lanes_root: Path
) -> None:
    """If the whole listing blocked for two seconds on `gh`, the redesign failed.

    Everything git can answer locally is collected up front; `pr` starts as a
    placeholder and the seam is handed a `fill` to replace it.
    """
    _two_lanes(projects_root, lanes_root)
    github = StubGitHubClient(found(PullRequest(number=7, state="MERGED", url="http://x/7")))
    context = _context(
        FakeUi([]), projects_root=projects_root, lanes_root=lanes_root, github=github
    )

    table = list_lanes.Table(context, context.lane_store().list_lanes(), {})
    table.collect()

    rows = table.rows()
    assert len(rows) == 2
    assert all(row.cells[2].text == "checking…" for row in rows)
    assert any("uncommitted" in row.cells[1].text for row in rows), "git was already asked"
    assert github.asked == [], "and GitHub was not"

    table.fill(lambda: None)

    assert all(row.cells[2].text == "#7 merged" for row in table.rows())
    assert len(github.asked) == 2


def test_a_pull_request_answer_is_not_asked_for_twice(
    projects_root: Path, lanes_root: Path
) -> None:
    """Closing one lane must not re-run `gh` for the lanes that are still there."""
    _two_lanes(projects_root, lanes_root)
    github = StubGitHubClient(found(PullRequest(number=7, state="OPEN", url="http://x/7")))
    context = _context(
        FakeUi([]), projects_root=projects_root, lanes_root=lanes_root, github=github
    )
    known: dict[str, list_lanes.PrCell] = {}

    for _ in range(2):
        table = list_lanes.Table(context, context.lane_store().list_lanes(), known)
        table.collect()
        table.fill(lambda: None)

    assert len(github.asked) == 2, "the second pass reused what the first learned"


# -- the panel ---------------------------------------------------------------------


def test_the_panel_carries_the_branch_which_no_longer_has_a_column(
    projects_root: Path, lanes_root: Path
) -> None:
    _two_lanes(projects_root, lanes_root)
    ui = FakeUi(["back"])

    list_lanes.run(_context(ui, projects_root=projects_root, lanes_root=lanes_root))

    panels = [told.text for told in ui.told if told.kind == "panel"]
    assert "chore/clean-lane" in panels
    assert "feature/busy-lane" in panels
    rows = " ".join(told.text for told in ui.told if told.kind == "row")
    assert "chore/clean-lane" not in rows, "and no longer a column"


def test_a_description_that_is_the_lane_name_again_is_not_repeated(
    projects_root: Path, lanes_root: Path
) -> None:
    """`improve-lint-and-format-performance` and `improve lint and format
    performance` are the same string twice. Rendering both buys nothing."""
    _origin, clone = build_repo(projects_root / "_b")
    repo = projects_root / "thing"
    clone.rename(repo)
    store = LaneStore(lanes_root)
    CliGitBackend().add_worktree_new_branch(
        repo,
        store.lane_path("thing", "improve-the-export"),
        "chore/improve-the-export",
        "origin/main",
    )
    store.write_meta(
        "thing",
        "improve-the-export",
        LaneMeta(description="Improve the export", base="main", repo=str(repo)),
    )

    ui = FakeUi(["back"])
    list_lanes.run(_context(ui, projects_root=projects_root, lanes_root=lanes_root))

    panels = [told.text for told in ui.told if told.kind == "panel"]
    assert "Improve the export" not in panels


def test_a_description_the_lane_name_could_not_keep_is_shown(
    projects_root: Path, lanes_root: Path
) -> None:
    """What makes them differ: transliteration, and the forty-character cap."""
    _origin, clone = build_repo(projects_root / "_b")
    repo = projects_root / "thing"
    clone.rename(repo)
    store = LaneStore(lanes_root)
    backend = CliGitBackend()
    for name, description in (
        ("login-sayfasi-hatasi", "Login sayfası hatası"),
        (
            "the-csv-export-drops-the-final-row-when-t",
            "The CSV export drops the final row when the file is large",
        ),
    ):
        backend.add_worktree_new_branch(
            repo, store.lane_path("thing", name), f"bugfix/{name[:20]}", "origin/main"
        )
        store.write_meta(
            "thing", name, LaneMeta(description=description, base="main", repo=str(repo))
        )

    ui = FakeUi(["back"])
    list_lanes.run(_context(ui, projects_root=projects_root, lanes_root=lanes_root))

    panels = [told.text for told in ui.told if told.kind == "panel"]
    assert "Login sayfası hatası" in panels, "the spelling the user typed"
    assert "The CSV export drops the final row when the file is large" in panels, (
        "the half the cap cut off"
    )


# -- acting on the row under the cursor --------------------------------------------


def test_choosing_a_row_then_enter_launches_the_editor_and_returns_to_the_menu(
    projects_root: Path, lanes_root: Path
) -> None:
    """Your attention has moved to the editor, so the listing gets out of the way."""
    _two_lanes(projects_root, lanes_root)
    environment = FakeEnvironment(tools={"git": "/g", "cursor": "/c"})
    ui = FakeUi(["busy-lane", "enter"])

    list_lanes.run(
        _context(
            ui,
            projects_root=projects_root,
            lanes_root=lanes_root,
            environment=environment,
        )
    )

    assert environment.launched == [("cursor", lanes_root / "thing" / "busy-lane")]
    assert ui.unanswered() == 0, "it did not come back and ask again"


def test_the_second_lane_can_be_selected_by_position(projects_root: Path, lanes_root: Path) -> None:
    """A script drives "select the second lane, close it" without naming it."""
    _two_lanes(projects_root, lanes_root)
    ui = FakeUi([1, "close", True, "back"])

    list_lanes.run(
        _context(
            ui,
            projects_root=projects_root,
            lanes_root=lanes_root,
            github=StubGitHubClient(NotApplicable("not-github")),
        )
    )

    # The order is project then name and never changes, so row 1 is clean-lane.
    assert not (lanes_root / "thing" / "clean-lane").exists()
    assert (lanes_root / "thing" / "busy-lane").exists()


def test_closing_leaves_you_in_the_listing_one_row_shorter(
    projects_root: Path, lanes_root: Path
) -> None:
    """Closing several lanes in a row is a real batch; going back to the menu
    between each is what made the old flow tiring."""
    _two_lanes(projects_root, lanes_root)
    ui = FakeUi(["clean-lane", "close", True, "back"])

    list_lanes.run(
        _context(
            ui,
            projects_root=projects_root,
            lanes_root=lanes_root,
            github=StubGitHubClient(NotApplicable("not-github")),
        )
    )

    assert not (lanes_root / "thing" / "clean-lane").exists()
    assert (lanes_root / "thing" / "busy-lane").exists(), "only the chosen lane closed"

    titles = [told.text for told in ui.told if told.kind == "table"]
    assert titles == ["2 open lanes in thing", "1 open lane in thing"]


def test_closing_the_last_lane_leaves_the_listing_with_nothing_to_show(
    projects_root: Path, lanes_root: Path
) -> None:
    _origin, clone = build_repo(projects_root / "_b")
    repo = projects_root / "thing"
    clone.rename(repo)
    store = LaneStore(lanes_root)
    CliGitBackend().add_worktree_new_branch(
        repo, store.lane_path("thing", "only"), "chore/only", "origin/main"
    )
    store.write_meta("thing", "only", LaneMeta(description="only", base="main", repo=str(repo)))

    ui = FakeUi(["only", "close", True])
    list_lanes.run(
        _context(
            ui,
            projects_root=projects_root,
            lanes_root=lanes_root,
            github=StubGitHubClient(NotApplicable("not-github")),
        )
    )

    assert ui.said("No open lanes")
    assert ui.unanswered() == 0


def test_backing_out_of_the_row_menu_returns_to_the_table(
    projects_root: Path, lanes_root: Path
) -> None:
    """The table is a screen you are standing in, not a question you were asked."""
    _two_lanes(projects_root, lanes_root)
    ui = FakeUi(["clean-lane", FakeUi.ABANDON, "back"])

    list_lanes.run(_context(ui, projects_root=projects_root, lanes_root=lanes_root))

    titles = [told.text for told in ui.told if told.kind == "table"]
    assert len(titles) == 2, "the table came back rather than the menu"
    assert ui.unanswered() == 0
    passes = [told for told in ui.told if told.kind == "progress"]
    assert len(passes) == 1, "and it came back as it was, without re-reading every lane"


def test_backing_out_of_a_close_returns_to_the_table_too(
    projects_root: Path, lanes_root: Path
) -> None:
    """Same reason as the row menu, and the same guarantee: a close asks everything
    before it removes anything, so backing out of any of it has changed nothing.
    Dropping to the main menu instead would punish a Ctrl-C during the fetch."""
    _two_lanes(projects_root, lanes_root)
    ui = FakeUi(["clean-lane", "close", FakeUi.ABANDON, "back"])

    list_lanes.run(
        _context(
            ui,
            projects_root=projects_root,
            lanes_root=lanes_root,
            github=StubGitHubClient(NotApplicable("not-github")),
        )
    )

    assert (lanes_root / "thing" / "clean-lane").exists(), "backing out changed nothing"
    titles = [told.text for told in ui.told if told.kind == "table"]
    assert len(titles) == 2, "the table came back rather than the menu"
    assert ui.unanswered() == 0


def test_the_cursor_stays_where_it_was_after_an_action(
    projects_root: Path, lanes_root: Path
) -> None:
    seen: list[int] = []

    class Recording(FakeUi):
        def browse(self, title, columns, rows, **kwargs):  # type: ignore[no-untyped-def]
            seen.append(kwargs.get("cursor", 0))
            return super().browse(title, columns, rows, **kwargs)

    _two_lanes(projects_root, lanes_root)
    ui = Recording([1, FakeUi.ABANDON, "back"])

    list_lanes.run(_context(ui, projects_root=projects_root, lanes_root=lanes_root))

    assert seen == [0, 1]


# -- and it is still fast with many lanes ------------------------------------------


def test_status_is_collected_across_a_thread_pool(projects_root: Path, lanes_root: Path) -> None:
    """Not a timing assertion — just that many lanes all come back correctly."""
    _origin, clone = build_repo(projects_root / "_b")
    repo = projects_root / "thing"
    clone.rename(repo)
    backend = CliGitBackend()
    store = LaneStore(lanes_root)
    for index in range(10):
        backend.add_worktree_new_branch(
            repo, store.lane_path("thing", f"lane{index}"), f"feature/l{index}", "origin/main"
        )

    rows = list_lanes.collect(
        _context(FakeUi([]), projects_root=projects_root, lanes_root=lanes_root),
        store.list_lanes(),
    )

    assert len(rows) == 10
    assert all(row.status is not None for row in rows)
    assert {row.status.branch for row in rows if row.status} == {
        f"feature/l{index}" for index in range(10)
    }

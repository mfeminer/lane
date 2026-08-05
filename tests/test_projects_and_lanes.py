"""Finding projects and lanes, and the diagnostics when there are none."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from lane.git.cli_backend import CliGitBackend
from lane.lanes import LaneMeta, LaneStore, age_phrase
from lane.projects import diagnose, find_nested_repository, list_projects
from tests.conftest import Origin, build_repo, git

# -- projects (H1, H2, H3) -------------------------------------------------------


def test_projects_are_the_direct_subdirectories_that_are_repositories(
    backend: CliGitBackend, projects_root: Path
) -> None:
    build_repo(projects_root / "alpha")
    build_repo(projects_root / "beta")
    (projects_root / "not-a-repo").mkdir()
    (projects_root / "a-file.txt").write_text("x")

    # build_repo nests the clone; point at the clones the way a real root does.
    root = projects_root / "flat"
    root.mkdir()
    for name in ("alpha", "beta"):
        git(["init", "--quiet", str(root / name)])
    (root / "plain").mkdir()

    found = list_projects(root, backend)

    assert [p.name for p in found] == ["alpha", "beta"]
    assert all(p.path.parent == root for p in found)


def test_a_missing_or_unset_projects_root_yields_nothing(
    backend: CliGitBackend, tmp_path: Path
) -> None:
    assert list_projects(None, backend) == []
    assert list_projects(tmp_path / "nowhere", backend) == []


def test_diagnosis_reports_how_many_subfolders_were_examined(
    backend: CliGitBackend, projects_root: Path
) -> None:
    for name in ("one", "two", "three"):
        (projects_root / name).mkdir()

    problem = diagnose(projects_root, backend)

    assert problem.root_exists
    assert problem.subdirectory_count == 3
    assert problem.nested_example is None


def test_diagnosis_spots_nested_repositories_and_suggests_the_right_root(
    backend: CliGitBackend, projects_root: Path
) -> None:
    """The classic mistake: <root>/<org>/<repo> instead of <root>/<repo>."""
    org = projects_root / "acme"
    org.mkdir()
    git(["init", "--quiet", str(org / "Acme.Widgets")])

    problem = diagnose(projects_root, backend)

    assert problem.nested_example == org / "Acme.Widgets"
    assert problem.suggested_root == org


def test_diagnosis_of_a_root_that_does_not_exist(backend: CliGitBackend, tmp_path: Path) -> None:
    problem = diagnose(tmp_path / "gone", backend)

    assert not problem.root_exists
    assert problem.subdirectory_count == 0


# -- lanes (H4, H5, H6) ----------------------------------------------------------


def test_lanes_are_discovered_as_worktrees_under_the_root(
    backend: CliGitBackend, repo: tuple[Origin, Path], lanes_root: Path
) -> None:
    _, clone = repo
    store = LaneStore(lanes_root)
    backend.add_worktree_new_branch(clone, store.lane_path("proj", "first"), "f/1", "origin/main")
    backend.add_worktree_detached(clone, store.lane_path("proj", "second"), "origin/main")
    # A stray directory that is not a worktree must not be listed.
    (lanes_root / "proj" / "junk").mkdir(parents=True, exist_ok=True)

    found = store.list_lanes()

    assert [(lane.project, lane.name) for lane in found] == [
        ("proj", "first"),
        ("proj", "second"),
    ]


def test_no_lanes_when_the_root_does_not_exist(lanes_root: Path) -> None:
    assert LaneStore(lanes_root).list_lanes() == []


def test_metadata_is_kept_outside_the_worktree_so_it_cannot_dirty_it(
    backend: CliGitBackend, repo: tuple[Origin, Path], lanes_root: Path
) -> None:
    _, clone = repo
    store = LaneStore(lanes_root)
    lane_path = store.lane_path("proj", "mylane")
    backend.add_worktree_new_branch(clone, lane_path, "feature/x", "origin/main")

    store.write_meta(
        "proj",
        "mylane",
        LaneMeta(
            description="Fix the export", base="main", created="2026-08-04 10:00", repo=str(clone)
        ),
    )

    # The metadata must not be inside the worktree...
    assert store.metadata_file("proj", "mylane").exists()
    assert store.metadata_dir("proj") not in lane_path.parents
    # ...and the worktree must still be clean.
    assert backend.status(lane_path, "main").dirty_count == 0


def test_metadata_round_trips(lanes_root: Path) -> None:
    store = LaneStore(lanes_root)
    meta = LaneMeta(
        description="Login sayfası hatası",
        base="dev",
        created="2026-08-01 09:30",
        repo="/Users/x/Projects/thing",
    )

    store.write_meta("proj", "lane", meta)

    assert store.read_meta("proj", "lane") == meta


def test_a_lane_without_metadata_still_lists_and_describes_itself(
    backend: CliGitBackend, repo: tuple[Origin, Path], lanes_root: Path
) -> None:
    """The worktree is the truth; the metadata is a convenience."""
    _, clone = repo
    store = LaneStore(lanes_root)
    backend.add_worktree_new_branch(clone, store.lane_path("p", "orphan"), "f/o", "origin/main")

    (lane,) = store.list_lanes()

    assert lane.meta == LaneMeta()
    assert lane.description() == "orphan"
    assert lane.repo_path(projects_root=Path("/somewhere")) == Path("/somewhere/p")


def test_forgetting_a_lane_removes_its_metadata_and_empty_directories(lanes_root: Path) -> None:
    store = LaneStore(lanes_root)
    store.write_meta("proj", "only", LaneMeta(description="d"))

    store.forget("proj", "only")

    assert not store.metadata_file("proj", "only").exists()
    assert not store.metadata_dir("proj").exists()
    assert not store.project_dir("proj").exists()


def test_forgetting_one_lane_leaves_a_sibling_alone(lanes_root: Path) -> None:
    store = LaneStore(lanes_root)
    store.write_meta("proj", "one", LaneMeta(description="a"))
    store.write_meta("proj", "two", LaneMeta(description="b"))

    store.forget("proj", "one")

    assert store.read_meta("proj", "two").description == "b"
    assert store.metadata_dir("proj").exists()


# -- lane age --------------------------------------------------------------------


def test_lane_age_is_derived_from_the_created_stamp(lanes_root: Path) -> None:
    store = LaneStore(lanes_root)
    created = datetime.now(UTC) - timedelta(days=9)
    store.write_meta(
        "p", "l", LaneMeta(description="d", created=created.strftime("%Y-%m-%d %H:%M"))
    )
    meta = store.read_meta("p", "l")

    assert meta.created_at is not None


def test_age_phrasing() -> None:
    assert age_phrase(None) == ""
    assert age_phrase(0) == "today"
    assert age_phrase(1) == "yesterday"
    assert age_phrase(3) == "3 days ago"
    assert age_phrase(10) == "last week"
    assert age_phrase(21) == "3 weeks ago"
    assert age_phrase(90) == "3 months ago"


def test_the_nested_finder_uses_the_same_definition_of_repository_as_the_listing(
    backend: CliGitBackend, projects_root: Path
) -> None:
    """Otherwise lane gives advice that contradicts what it just reported.

    A folder with a stray `.git` entry that is not a repository must not be
    offered as "your repositories look nested".
    """
    decoy = projects_root / "org" / "not-really-a-repo"
    decoy.mkdir(parents=True)
    (decoy / ".git").write_text("this is not a gitdir pointer\n")

    assert find_nested_repository(projects_root, backend) is None


def test_the_nested_finder_still_finds_a_genuine_nested_repository(
    backend: CliGitBackend, projects_root: Path
) -> None:
    org = projects_root / "acme"
    org.mkdir()
    git(["init", "--quiet", str(org / "Acme.Widgets")])

    assert find_nested_repository(projects_root, backend) == org / "Acme.Widgets"


def test_projects_are_found_through_a_differently_cased_root(
    backend: CliGitBackend, projects_root: Path
) -> None:
    """The bug a user hit: typing the root in lowercase found nothing at all."""
    git(["init", "--quiet", str(projects_root / "alpha")])
    git(["init", "--quiet", str(projects_root / "beta")])

    swapped = Path(str(projects_root).upper())
    if not swapped.is_dir():
        return  # a case-sensitive filesystem; nothing to test

    assert len(list_projects(swapped, backend)) == 2

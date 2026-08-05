"""Open a lane: its own worktree, branch and editor window.

**Everything is asked before anything is created.** Project, description, mode,
branch — all of it — and only then does the worktree appear. That is what makes
backing out at any prompt a clean no-op, and it is why there is no rollback logic
here to get wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lane.actions.picking import choose_project
from lane.context import Context
from lane.git.backend import GitError
from lane.lanes import LaneMeta, LaneStore
from lane.naming import sanitize_branch, slugify
from lane.ui.seam import Choice

BRANCH_PREFIXES = ("feature", "bugfix", "hotfix", "chore", "refactor", "docs")

_OTHER = "\x00other\x00"
_BARE = "\x00bare\x00"


@dataclass(frozen=True, slots=True)
class _Plan:
    """Every decision, gathered before the first irreversible step."""

    project: str
    repo_path: Path
    lane_name: str
    description: str
    base: str
    start_point: str
    branch: str | None
    """None means detached."""


def run(context: Context) -> None:
    plan = _gather(context)
    if plan is None:
        return
    _execute(context, plan)


def _gather(context: Context) -> _Plan | None:
    ui = context.ui

    project = choose_project(context, "Which project?")
    if project is None:
        return None

    if not context.git.is_repository(project.path):
        ui.error(f"Not a git repository: {project.path}")
        return None

    description = ui.text("What are you working on")
    if not description.strip():
        ui.error("A lane needs a description.")
        return None

    lane_name = slugify(description)
    if not lane_name:
        ui.error("Could not derive a lane name from that description.")
        ui.detail("  Lane names must be plain ASCII — try wording it differently.")
        return None

    store = context.lane_store()
    lane_path = store.lane_path(project.name, lane_name)
    if lane_path.exists():
        ui.error(f"That lane is already open: {lane_path}")
        return None

    fetch = ui.progress("Fetching origin…", lambda: context.git.fetch_prune(project.path))
    if not fetch.ok:
        ui.warn("Fetch failed (offline?) — falling back to local refs.")

    base = context.git.default_branch(project.path)
    if base is None:
        # Deliberately not guessed: basing a lane on the wrong branch silently is
        # worse than refusing. See ADR 0001.
        ui.error("Could not determine the default branch for this repository.")
        ui.detail("  Check `git remote show origin`, or set origin/HEAD with:")
        ui.detail("    git remote set-head origin --auto")
        return None

    start_point = f"origin/{base}"
    if not context.git.rev_parse_verify(project.path, start_point):
        start_point = base

    ui.blank()
    ui.info(f"  Project   : {project.name}")
    ui.info(f"  Lane      : {lane_name}")
    ui.info(f"  Task      : {description}")
    ui.info(f"  Path      : {lane_path}")
    ui.info(f"  Starts at : {start_point}")
    ui.blank()

    mode = ui.choose(
        "How should this lane start?",
        [
            Choice("branch", "branch", "start on a new branch now"),
            Choice("detached", "detached", f"sit at {start_point} with no branch"),
        ],
    )

    branch: str | None = None
    if mode == "branch":
        branch = _choose_branch(context, lane_name)
        if branch is None:
            return None

    return _Plan(
        project=project.name,
        repo_path=project.path,
        lane_name=lane_name,
        description=description,
        base=base,
        start_point=start_point,
        branch=branch,
    )


def _choose_branch(context: Context, lane_name: str) -> str | None:
    """Branch naming is per lane, deliberately not a global setting.

    One lane can be `bugfix/…` while the next is `feature/…`: the prefix describes
    the task, not the machine.
    """
    ui = context.ui
    options: list[Choice[str]] = [
        Choice(f"{prefix}/{lane_name}", f"{prefix}/{lane_name}") for prefix in BRANCH_PREFIXES
    ]
    options.append(Choice(lane_name, _BARE, "no prefix"))
    options.append(Choice("other…", _OTHER, "type a branch name"))

    while True:
        chosen = ui.choose("Branch name", options)
        if chosen == _BARE:
            candidate = lane_name
        elif chosen == _OTHER:
            candidate = ui.text("Branch name", default=f"feature/{lane_name}")
        else:
            candidate = chosen

        branch = sanitize_branch(candidate)
        if not branch:
            ui.error("That is not a usable branch name.")
            continue
        if not context.git.check_ref_format(branch):
            # git owns this judgement; lane does not second-guess it.
            ui.error(f"git rejects that branch name: {branch}")
            continue
        if branch != candidate:
            ui.detail(f"  Using: {branch}")
        return branch


def _execute(context: Context, plan: _Plan) -> None:
    """The first irreversible step, and everything after it."""
    ui = context.ui
    store: LaneStore = context.lane_store()
    lane_path = store.lane_path(plan.project, plan.lane_name)
    repo = plan.repo_path

    try:
        if plan.branch is None:
            context.git.add_worktree_detached(repo, lane_path, plan.start_point)
        elif context.git.branch_exists(repo, plan.branch):
            ui.warn(f"Branch '{plan.branch}' already exists — checking it out as is.")
            context.git.add_worktree_existing_branch(repo, lane_path, plan.branch)
        else:
            context.git.add_worktree_new_branch(repo, lane_path, plan.branch, plan.start_point)
    except GitError as exc:
        ui.error(f"Could not create the worktree: {exc}")
        return

    # The starting commit is what later tells "this lane has done no work" apart
    # from "this lane's work has landed": both leave nothing ahead of origin/<base>.
    try:
        start = context.git.head_commit(lane_path)
    except GitError:
        start = ""

    store.write_meta(
        plan.project,
        plan.lane_name,
        LaneMeta(
            description=plan.description,
            base=plan.base,
            created=LaneStore.timestamp(),
            repo=str(repo),
            start=start,
        ),
    )
    context.state_store.remember_project(plan.project)

    suffix = f"  ({plan.branch})" if plan.branch else "  (detached)"
    ui.ok(f"Lane open: {plan.project}/{plan.lane_name}{suffix}")
    ui.detail(f"  {lane_path}")
    if plan.branch is not None:
        # The missing upstream is the invariant; tell the user how to push the
        # first time so the absence does not read as a bug.
        ui.detail(f"  Push the first time with: git push -u origin {plan.branch}")

    launch = context.environment.launch_editor(context.config.editor, lane_path)
    if launch.launched:
        ui.ok(launch.detail)
    else:
        ui.warn(f"{launch.detail} — open the lane yourself: {lane_path}")
        ui.detail("  Change the editor command in settings.")

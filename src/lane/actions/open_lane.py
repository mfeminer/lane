"""Open a lane: its own worktree, branch and editor window.

**Everything is asked before anything is created.** Project, kind, description,
mode, branch — all of it — and only then does the worktree appear. That is what
makes backing out at any prompt a clean no-op, and it is why there is no rollback
logic here to get wrong.

**Opening a lane is not always new work.** Picking up a branch a colleague pushed,
coming back to something abandoned, reviewing a pull request locally — all of them
start from a branch that is already there. So after the project comes one question
with two answers, and then the flows diverge:

* **new work** — description, lane name, mode, branch, exactly as before.
* **existing branch** — pick the branch; the lane takes its name and its
  description from that rather than asking for them again.

Detached mode belongs to the new-work path alone: an existing branch is the
opposite of detached, so the mode question is never reached on the second path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from lane.actions import enter_lane
from lane.actions.picking import choose_project
from lane.context import Context
from lane.git.backend import BranchRef, GitError
from lane.lanes import Lane, LaneMeta, LaneStore, age_phrase
from lane.naming import sanitize_branch, slugify
from lane.paths import same_directory
from lane.projects import Project
from lane.ui.seam import Cell, Choice, Column, Row

KIND_QUESTION = "What is this lane for?"
NAME_QUESTION = "Lane name"
DESCRIPTION_QUESTION = "What are you working on"
MODE_QUESTION = "How should this lane start?"
BRANCH_NAME_QUESTION = "Branch name"

# What each question is *called*, so a flag can answer it before it is drawn. Names,
# not titles: the titles above are prose, and docs/CONVENTIONS.md §8 expects them to be
# reworded — a reword must not silently re-route a flag (`cli.answers`).
KIND = "kind"
DESCRIPTION = "description"
MODE = "mode"
BRANCH_NAME = "branch-name"
BRANCH_NAME_TYPED = "branch-name-typed"
BRANCH = "branch"
LANE_NAME = "lane-name"
ENTER_INSTEAD = "enter-that-lane"

BRANCH_COLUMNS = (
    Column("branch"),
    # Can I take this, and what happens if I do. The screen's own question, so it is
    # never dropped and never truncated — the lanes table's rule (CONVENTIONS §13).
    Column("state"),
    Column("age", drop=1),
)

OTHER = "\x00other\x00"
"""The escape from the branch menu into typing one. Public because `--branch-name`
means *that* choice followed by *that* answer: one flag, the two keystrokes a person
would have made. The alternative — teaching the seam that this picker has a free-text
escape — would put a screen's shape into the thing that answers screens."""
_BARE = "\x00bare\x00"
NEW = "\x00new\x00"
EXISTING = "\x00existing\x00"


@dataclass(frozen=True, slots=True)
class Opened:
    """What opening a lane came to. Read by `--json`; ignored by the menu."""

    project: str
    lane: str
    path: Path
    branch: str | None
    """None means detached."""

    base: str
    start: str
    adopted: bool
    """The branch was already there and this lane took it up."""

    entered: enter_lane.Entered


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

    existing: bool = False
    """The user picked this branch because it was already there.

    Distinct from merely finding that the branch exists, which the new-work path can
    also do by collision: this says the branch is what the user chose, so checking it
    out as it stands is the plan rather than a surprise worth warning about.
    """


def run(context: Context) -> None:
    """The menu's way in. It ignores the outcome, because it has a screen to go back to."""
    open_a_lane(context)


def open_a_lane(context: Context, *, launch_editor: bool = True) -> Opened | None:
    """Open a lane and say what came of it. `None` means it was refused, having said why.

    The return value exists for `lane open --json`, which cannot recover an outcome
    from prose. It is the same decision either way — one code path, rendered twice —
    and the menu simply drops it.
    """
    plan = _gather(context)
    if plan is None:
        return None
    return _execute(context, plan, launch_editor=launch_editor)


def _gather(context: Context) -> _Plan | None:
    ui = context.ui

    project = choose_project(context, "Which project?")
    if project is None:
        return None

    if not context.git.is_repository(project.path):
        ui.error(f"Not a git repository: {project.path}")
        return None

    kind = ui.choose(
        KIND_QUESTION,
        [
            Choice("new work", NEW, "describe the task; lane makes the branch"),
            Choice("existing branch", EXISTING, "pick up a branch that is already there"),
        ],
        key=KIND,
    )
    if kind == EXISTING:
        return _gather_existing(context, project)
    return _gather_new(context, project)


def _gather_new(context: Context, project: Project) -> _Plan | None:
    """New work: the flow lane has always had, unchanged from here down."""
    ui = context.ui

    description = ui.text(DESCRIPTION_QUESTION, key=DESCRIPTION)
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

    base = _fetch_and_resolve_base(context, project)
    if base is None:
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
        MODE_QUESTION,
        [
            Choice("branch", "branch", "start on a new branch now"),
            Choice("detached", "detached", f"sit at {start_point} with no branch"),
        ],
        key=MODE,
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


# -- picking up a branch that is already there -----------------------------------


def _gather_existing(context: Context, project: Project) -> _Plan | None:
    """The branch answers what the description would have been asked for."""
    base = _fetch_and_resolve_base(context, project)
    if base is None:
        return None

    branch = _pick_branch(context, project)
    if branch is None:
        return None

    lane_name = _ask_lane_name(context, project, branch)
    if lane_name is None:
        return None

    return _Plan(
        project=project.name,
        repo_path=project.path,
        lane_name=lane_name,
        # The branch is the description: the user typed nothing, and this is what
        # they chose. The listing's panel already drops a description that repeats
        # the name, and now drops one that repeats the branch line too.
        description=branch.name,
        base=base,
        # Only read for a branch that has to be created locally, and then it is the
        # remote ref the new local branch tracks.
        start_point=f"origin/{branch.name}",
        branch=branch.name,
        existing=True,
    )


def _pick_branch(context: Context, project: Project) -> BranchRef | None:
    """The branch list, and the refusals that belong to it.

    A `browse` rather than a `choose`, decided on measurement rather than taste: the
    picker draws every option into one window with no scrolling of its own, so three
    hundred branches is three hundred lines with the cursor walking off the bottom of
    the terminal. The table windows the same list and says which slice you are
    looking at. A branch row also carries four facts, and looking at them and acting
    on them is one activity — the same argument that shaped the lanes screen.

    **Unavailable branches are shown, not hidden.** Prerequisites are enforced where
    they are used; a row that is not there cannot explain why it is not there, and
    the branch the user wants is very often exactly the one another lane has.
    """
    ui = context.ui

    # No empty-state branch here, deliberately: `_fetch_and_resolve_base` has already
    # refused when there is no default branch, and a repository that has one has at
    # least that branch to list. An empty list is unreachable, so there is no
    # untested code standing in for it.
    branches = context.git.list_branches(project.path)
    held = context.git.checkouts(project.path)
    lanes = context.lane_store().list_lanes()

    def rows() -> list[Row[BranchRef]]:
        return [_branch_row(branch, project.path, held, lanes) for branch in branches]

    count = len(branches)
    title = f"{count} branch{'es' if count != 1 else ''} in {project.name}"

    cursor = 0
    while True:
        chosen, cursor = ui.browse(title, BRANCH_COLUMNS, rows, cursor=cursor, key=BRANCH)

        holder = held.get(chosen.name)
        if holder is None:
            return chosen

        # git refuses to check a branch out twice. Refusing here, with the reason,
        # is the same refusal made useful — and it does not leave the screen, which
        # is one the user is standing in.
        lane = _lane_at(lanes, holder)
        if lane is None:
            where = (
                "in the main clone"
                if same_directory(holder, project.path)
                else "in another worktree"
            )
            ui.error(f"'{chosen.name}' is checked out {where}, so git cannot check it out again.")
            ui.detail(f"  {holder}")
            continue

        ui.error(f"'{chosen.name}' is open in the lane {lane.slug}.")
        if not ui.confirm("Enter that lane instead?", key=ENTER_INSTEAD):
            continue
        # A better answer than an error: the lane the user is looking for already
        # exists. Nothing has been created, so this is a clean way out of `open`.
        enter_lane.enter(context, lane)
        return None


def _branch_row(
    branch: BranchRef, repo: Path, held: dict[str, Path], lanes: list[Lane]
) -> Row[BranchRef]:
    return Row(
        value=branch,
        cells=(Cell(branch.name), _where_cell(branch, repo, held, lanes), _age_cell(branch)),
    )


def _where_cell(branch: BranchRef, repo: Path, held: dict[str, Path], lanes: list[Lane]) -> Cell:
    """Can I take this, and what happens if I do — in words, never colour alone.

    Three ways a branch can be taken, and they are told apart by asking rather than by
    elimination: not every worktree is one of lane's, so "it is not a lane" is not the
    same as "it is the main clone" — a user can make one by hand, and a lane removed
    from underneath git leaves an entry behind until something prunes it. Naming the
    wrong place sends the user to look in it.
    """
    holder = held.get(branch.name)
    if holder is not None:
        lane = _lane_at(lanes, holder)
        if lane is not None:
            return Cell(f"in lane {lane.slug}", tone="warn", short="a lane")
        if same_directory(holder, repo):
            return Cell("in the main clone", tone="warn", short="main clone")
        return Cell("in another worktree", tone="warn", short="a worktree")
    if branch.remote_only:
        # Not unavailable — taking it creates a local branch that tracks the remote.
        return Cell("origin only", tone="dim", short="origin")
    return Cell("")


def _age_cell(branch: BranchRef) -> Cell:
    if not branch.committed:
        return Cell("", tone="dim")
    days = max(0, (int(datetime.now(UTC).timestamp()) - branch.committed) // 86400)
    return Cell(age_phrase(days), tone="dim")


def _lane_at(lanes: list[Lane], path: Path) -> Lane | None:
    """Which lane lives at this worktree path.

    Asked of the filesystem, never compared as strings: `git worktree list` reports
    the case on disk while a lanes root keeps whichever case the user typed, and
    comparing those two as strings once made every project vanish.
    """
    for lane in lanes:
        if same_directory(lane.path, path):
            return lane
    return None


def _ask_lane_name(context: Context, project: Project, branch: BranchRef) -> str | None:
    """The derived name, shown for editing rather than simply used.

    On the new-work path the name renders a sentence the user typed a moment ago for
    exactly this purpose. Here it is derived from a string somebody else chose for
    another one, so the forty-character cap cuts it in a place nobody chose — and the
    lane name is a directory the user is about to live in. It is also the only place
    a collision can be resolved: unlike a description, a branch name cannot be
    reworded, so refusing outright would strand them.

    The prefix is deliberately **not** stripped. It would buy about seven characters
    of the cap and cost a whole class of collision — `feature/x` and `bugfix/x` both
    reduce to `x`, and a lane name is a directory name.
    """
    ui = context.ui
    store = context.lane_store()

    default = slugify(branch.name)
    if not default:
        ui.error(f"Could not derive a lane name from '{branch.name}'.")
        ui.detail("  Lane names must be plain ASCII.")
        return None

    while True:
        name = slugify(ui.text(NAME_QUESTION, default=default, key=LANE_NAME))
        if not name:
            ui.error("Could not derive a lane name from that.")
            continue
        lane_path = store.lane_path(project.name, name)
        if lane_path.exists():
            ui.error(f"That lane is already open: {lane_path}")
            continue
        return name


def _fetch_and_resolve_base(context: Context, project: Project) -> str | None:
    """Both paths need this, and the existing-branch one cannot list without it.

    Fetching with `--prune` is what stops the list offering branches deleted on the
    remote weeks ago, and it is slow enough to need saying so.
    """
    ui = context.ui

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
    return base


def _choose_branch(context: Context, lane_name: str) -> str | None:
    """Branch naming is per lane, deliberately not a global setting.

    One lane can be `bugfix/…` while the next is `feature/…`: the prefix describes
    the task, not the machine. **That is about the choice, and it is untouched.**

    What the choice is made *from* is a setting, and lives in `branch_prefixes.toml`
    (config · branch prefixes). A team whose branches are `spike/` and `poc/` had to
    reach for `other…` every time — a free-text prompt standing in for a list lane could
    perfectly well have offered. The store always answers with at least one prefix, the
    six lane ships with when nothing has been customised.
    """
    ui = context.ui
    prefixes = context.prefix_store().load()
    options: list[Choice[str]] = [
        Choice(f"{prefix}/{lane_name}", f"{prefix}/{lane_name}") for prefix in prefixes
    ]
    options.append(Choice(lane_name, _BARE, "no prefix"))
    options.append(Choice("other…", OTHER, "type a branch name"))

    while True:
        chosen = ui.choose(BRANCH_NAME_QUESTION, options, key=BRANCH_NAME)
        if chosen == _BARE:
            candidate = lane_name
        elif chosen == OTHER:
            # Something the menu itself would have offered — offering `feature/` to
            # somebody who has just forgotten `feature` is the one wrong default.
            candidate = ui.text(
                BRANCH_NAME_QUESTION, default=f"{prefixes[0]}/{lane_name}", key=BRANCH_NAME_TYPED
            )
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


def _starting_commit(context: Context, lane_path: Path, base: str) -> str:
    """Where everything on HEAD stops being the base's work and starts being this
    branch's.

    **One rule for both paths**, which is what keeps this from being two. A branch
    lane created starts at `origin/<base>`, so its merge base with the base *is* its
    head commit — exactly the value recorded before this existed. A branch lane
    adopted arrives with commits already on it, and they are not nothing: recording
    the tip instead would make the listing say `no commits yet` about a branch full
    of unmerged work, and make the close flow file "no commits of its own — nothing
    to merge" as a clean note directly above the confirmation that deletes them.

    Falls back to the head commit when the base is not here to be compared against,
    which is the weaker answer this already gave when the read failed.
    """
    try:
        found = context.git.merge_base(lane_path, "HEAD", f"origin/{base}")
        if found:
            return found
        return context.git.head_commit(lane_path)
    except GitError:
        return ""


def _execute(context: Context, plan: _Plan, *, launch_editor: bool = True) -> Opened | None:
    """The first irreversible step, and everything after it."""
    ui = context.ui
    store: LaneStore = context.lane_store()
    lane_path = store.lane_path(plan.project, plan.lane_name)
    repo = plan.repo_path

    try:
        if plan.branch is None:
            context.git.add_worktree_detached(repo, lane_path, plan.start_point)
        elif context.git.branch_exists(repo, plan.branch):
            if not plan.existing:
                # A collision rather than a choice: the user asked for a new branch
                # and one of that name was already here.
                ui.warn(f"Branch '{plan.branch}' already exists — checking it out as is.")
            context.git.add_worktree_existing_branch(repo, lane_path, plan.branch)
        elif plan.existing:
            # Only on the remote so far, so the local branch is created here — and it
            # tracks `origin/<itself>`, which is what makes its unpushed count a real
            # measurement and cannot reach the default branch.
            context.git.add_worktree_tracking_branch(repo, lane_path, plan.branch, plan.start_point)
        else:
            context.git.add_worktree_new_branch(repo, lane_path, plan.branch, plan.start_point)
    except GitError as exc:
        ui.error(f"Could not create the worktree: {exc}")
        return None

    start = _starting_commit(context, lane_path, plan.base)

    meta = LaneMeta(
        description=plan.description,
        base=plan.base,
        created=LaneStore.timestamp(),
        repo=str(repo),
        start=start,
    )
    store.write_meta(plan.project, plan.lane_name, meta)
    context.state_store.remember_project(plan.project)

    suffix = f"  ({plan.branch})" if plan.branch else "  (detached)"
    ui.ok(f"Lane open: {plan.project}/{plan.lane_name}{suffix}")
    ui.detail(f"  {lane_path}")
    if plan.branch is not None and not plan.existing:
        # The missing upstream is a decision lane made, so lane explains it: without
        # this the absence reads as a bug. A branch lane *adopted* had nothing
        # withheld from it — it already tracks `origin/<itself>` — so this would be
        # advice for a situation the user is not in. Where an adopted local branch
        # genuinely has no upstream, git's own push message says so far better than
        # lane can guess.
        ui.detail(f"  Push the first time with: git push -u origin {plan.branch}")

    # And now the same thing that happens whenever you go into a lane: make it ready,
    # then open the editor. One code path rather than two — the launch and its
    # missing-editor warning used to exist here as well, and could drift.
    #
    # Preparation asks its own questions, and they come after the worktree exists. That
    # is not a breach of *every question comes before the first irreversible step*:
    # abandoning them leaves a complete lane that is merely unprepared, which the
    # listing shows, the close flow can act on, and the next enter repairs.
    entered = enter_lane.enter(
        context,
        Lane(project=plan.project, name=plan.lane_name, path=lane_path, meta=meta),
        launch_editor=launch_editor,
    )

    return Opened(
        project=plan.project,
        lane=plan.lane_name,
        path=lane_path,
        branch=plan.branch,
        base=plan.base,
        start=start,
        adopted=plan.existing,
        entered=entered,
    )

"""The lane listing: one screen, with the cursor on the thing you are about to act on.

Two questions, and the screen answers both without being asked for anything:

1. What am I in the middle of?
2. Which of these can I close, and what is stopping the ones that cannot?

Question 2 is what shapes the layout. `state` and `pr` carry the answer, so they
get the room and are never dropped; `branch` lost its column because it was the
lane name with a prefix in front of it, and lives in the panel instead. ADR 0002
has the reasoning, including why looking and acting are the same widget now.

**Two speeds.** Git status is local and fast, so it is collected before the first
paint. Pull request state is **two** `gh` processes per lane and is not, so the `pr`
column opens as `checking…` and fills in behind the screen you are already using. If
the listing ever blocks on a `gh` round trip, this has been broken.

The second process asks what is *based on* this branch, which `--head` cannot see and
which decides whether the lane can close at all. It costs a process rather than a
field because it is a different query, and it is affordable for the same reason as the
first: nothing waits for either.

`state` is drawn from the row on every repaint rather than computed once, because it
reads the pull request answer: a squash merge puts the lane's commits nowhere in the
base, so only GitHub can tell that the work landed. Compute it before the fill and
`state` goes back to saying `not merged yet` beside a `pr` cell reading `merged`.
"""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace

from lane.actions import enter_lane
from lane.actions.picking import resolve_base
from lane.context import Context
from lane.git.backend import GitError, WorktreeStatus
from lane.github.client import CannotTell, Dependents, Found, NoPullRequest, NotApplicable
from lane.lanes import Lane, age_phrase
from lane.ui.seam import Abandoned, Cell, Choice, Column, Row, Tone

_MAX_WORKERS = 8

BACK = "← Back to the menu"

COLUMNS = (
    Column("lane"),
    Column("state"),
    Column("pr"),
    # The only column the listing can do without: it answers neither question.
    Column("age", drop=1),
)


@dataclass(frozen=True, slots=True)
class PrCell:
    """What the `pr` column says, and the sentence the panel adds to it."""

    text: str
    tone: Tone
    note: str = ""

    merged: bool = False
    """GitHub says the work landed — the one thing `state` cannot see for itself.

    A squash or rebase merge rewrites the lane's commits, so no ancestry check will
    ever find them in the base. `state` reads this rather than contradicting it.
    """

    stacked: tuple[int, ...] = ()
    """Numbers of the open pull requests based on this lane's branch.

    Read by `state`, not drawn in `pr`: this column is the lane's own pull requests,
    and a review stacked on the branch is somebody else's. It belongs in `state`
    because it changes what closing does — the branch is about to be deleted, and
    these are built on it.
    """

    after_merge: int | None = None
    """Commits made after the decisive pull request merged, when that is knowable.

    Also read by `state`, and for the same kind of reason: once the remote branch is
    deleted there is no upstream to measure against, so the unpushed count falls back
    to the base and counts the very commits the squash merge landed. Zero here is the
    pull request saying it carried all of them. None means it could not be established
    — never confuse that with zero.
    """


PENDING = PrCell("checking…", "dim", "Checking GitHub for a pull request…")
"""What `pr` says before `gh` has answered. Never what it settles on."""


@dataclass
class LaneRow:
    lane: Lane
    status: WorktreeStatus | None
    problem: str = ""
    pr: PrCell = PENDING


def collect(context: Context, lanes: list[Lane]) -> list[LaneRow]:
    """Every lane's git status, concurrently. **No `gh` call happens here.**

    Each lane costs several `git` calls and subprocesses release the GIL, so the
    thread pool is what keeps this quick with many lanes (measured 5x on twelve;
    see ADR 0001).
    """
    if not lanes:
        return []

    def one(lane: Lane) -> LaneRow:
        base = resolve_base(context, lane)
        if base is None:
            return LaneRow(lane=lane, status=None, problem="no default branch")
        try:
            status = context.git.status(lane.path, base, lane.meta.start)
        except GitError as exc:
            return LaneRow(lane=lane, status=None, problem=str(exc)[:40])
        return LaneRow(lane=lane, status=status)

    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(lanes))) as pool:
        return list(pool.map(one, lanes))


class Table:
    """The rows, and the slow column that arrives after them.

    `rows()` is read on every repaint and `fill()` is handed to the seam, which
    decides whether to run it on a thread. Nothing here knows a terminal exists.
    """

    def __init__(self, context: Context, lanes: list[Lane], known: dict[str, PrCell]) -> None:
        self._context = context
        self._lanes = lanes
        self._known = known
        """Answers already paid for. Closing a lane must not re-run `gh` for the rest."""

        self._lock = threading.Lock()
        self._rows: list[LaneRow] = []
        self._bare = len({lane.project for lane in lanes}) == 1
        """One project shared by every lane, so the title can carry it."""

    @property
    def title(self) -> str:
        count = len(self._lanes)
        word = "lane" if count == 1 else "lanes"
        if self._bare and self._lanes:
            return f"{count} open {word} in {self._lanes[0].project}"
        return f"{count} open {word}"

    def collect(self) -> None:
        rows = collect(self._context, self._lanes)
        for row in rows:
            cached = self._known.get(row.lane.slug)
            if cached is not None:
                row.pr = cached
        with self._lock:
            self._rows = rows

    def rows(self) -> list[Row[Lane]]:
        with self._lock:
            return [self._draw(row) for row in self._rows]

    def fill(self, notify: object) -> None:
        """Ask GitHub about each lane still showing a placeholder."""
        assert callable(notify)
        with self._lock:
            outstanding = [row for row in self._rows if row.pr is PENDING]
        if not outstanding:
            return

        def one(row: LaneRow) -> None:
            cell = _pr_cell(self._context, row.lane, row.status)
            with self._lock:
                row.pr = cell
            self._known[row.lane.slug] = cell
            notify()

        with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(outstanding))) as pool:
            list(pool.map(one, outstanding))

    def _draw(self, row: LaneRow) -> Row[Lane]:
        return Row(
            value=row.lane,
            cells=(
                Cell(row.lane.name, lead="" if self._bare else f"{row.lane.project}/"),
                _state_cell(row),
                Cell(row.pr.text, tone=row.pr.tone),
                Cell(age_phrase(row.lane.age_days()), tone="dim"),
            ),
            detail=_detail(row),
        )


def _state_cell(row: LaneRow) -> Cell:
    """What the lane looks like, in words that do not overclaim.

    `merged` is only said when the lane actually has commits that reached the base.
    A lane opened a minute ago sits exactly at `origin/<base>`, so an ancestry check
    calls it merged — vacuously, since it has never had anything to merge. Saying so
    invited the reader to believe their work had landed.

    A `MERGED` pull request counts as reaching the base even when git's ancestry
    check disagrees — the squash and rebase case, which no amount of fetching can
    resolve because the lane's commits genuinely are not in the base any more. This
    is the rule the close flow has always applied; reading it here is what stops
    `state` saying "not merged yet" beside a `pr` cell that says `merged`.
    """
    if row.status is None:
        # The specific reason is worth the room when there is room; abbreviated it
        # is just "something is wrong here", which "unreadable" already says.
        return Cell(row.problem or "unreadable", tone="bad", short="unreadable")

    status = row.status
    parts: list[str] = []
    shorts: list[str] = []
    if status.dirty_count:
        parts.append(f"● {status.dirty_count} uncommitted")
        shorts.append(f"●{status.dirty_count}")
    unpushed = 0 if _counts_landed_work(row) else status.unpushed_count
    if unpushed:
        parts.append(f"↑ {unpushed} unpushed")
        shorts.append(f"↑{unpushed}")
    if row.pr.stacked:
        # Not the lane's own work, but it decides whether the lane can close: the
        # branch goes when it does, and these are based on it.
        parts.append(f"↳ {len(row.pr.stacked)} stacked")
        shorts.append(f"↳{len(row.pr.stacked)}")
    # `has_own_commits` still gates it, for the pull request route too: a lane that
    # never committed has landed nothing, whatever GitHub was asked about its branch.
    landed = status.landed or (row.pr.merged and status.has_own_commits)
    if landed:
        # Not a blocker, but worth saying alongside them: it means the work landed
        # and whatever is left here is incidental.
        parts.append("✓ merged")
        shorts.append("✓")

    if parts:
        blocked = bool(status.dirty_count or unpushed or row.pr.stacked)
        text, tone = " · ".join(parts), ("warn" if blocked else "good")
        # `✓ merged` alone is already short; abbreviating it to a bare `✓` reads as
        # nothing at all without a count next to it to anchor it.
        short = text if parts == ["✓ merged"] else " ".join(shorts)
    elif not status.has_own_commits:
        text, tone, short = "no commits yet", "dim", "no commits"
    else:
        text, tone, short = "not merged yet", "warn", "not merged"

    if status.detached:
        # There is no branch to delete and unpushed commits strand, so detachment
        # changes what closing does — which makes it a state, not a name.
        return Cell(f"detached · {text}", tone="warn", short=f"detached {short}")
    return Cell(text, tone=tone, short=short)  # type: ignore[arg-type]


def _counts_landed_work(row: LaneRow) -> bool:
    """Whether this lane's unpushed count is measuring commits that in fact landed.

    Only ever true with no upstream: that is when the count falls back to the base,
    which a squash merge leaves the lane's commits out of. `after_merge == 0` is the
    pull request saying it carried all of them. Anything else — a live upstream, an
    open pull request, a count that could not be established — and the number stands.
    """
    return (
        row.status is not None
        and row.status.upstream is None
        and row.pr.merged
        and row.pr.after_merge == 0
    )


def _after_merge(context: Context, lane: Lane, history: Found) -> int | None:
    """How much of this branch was committed after its pull request merged.

    Paid for during the fill, where the `gh` call already is — so it costs the first
    paint nothing, and the panel still makes no call of its own.
    """
    if not history.landed:
        return None
    try:
        return context.git.commits_since(lane.path, history.decisive.head_oid)
    except GitError:
        return None


def _pr_cell(context: Context, lane: Lane, status: WorktreeStatus | None) -> PrCell:
    """Both questions about this lane's branch, and the cell they make between them.

    Two `gh` processes per lane, not one — see AGENTS.md. Both are paid for here, in
    the fill, behind the screen the user is already reading; neither may be moved in
    front of the first paint.

    Never raises: an unavailable `gh` is a cell, not a failure to render.
    """
    if status is None:
        return PrCell("—", "dim")

    repo = lane.repo_path(context.projects_root)
    try:
        remote_url = context.git.remote_url(repo)
    except GitError:
        remote_url = None

    return _add_what_is_stacked_on_it(
        context, lane, status, remote_url, _own_pr_cell(context, lane, status, remote_url)
    )


def _add_what_is_stacked_on_it(
    context: Context,
    lane: Lane,
    status: WorktreeStatus,
    remote_url: str | None,
    cell: PrCell,
) -> PrCell:
    """Whatever is based on this branch, added to the cell its own pull requests made.

    Independent of that answer, so it applies whichever way it went: a lane can have no
    pull request of its own and still be the base of somebody else's.
    """
    try:
        answer = context.github.pull_requests_based_on(
            branch=status.branch, remote_url=remote_url, cwd=lane.path
        )
    except Exception:
        return cell

    if not isinstance(answer, Dependents) or not answer.pull_requests:
        # `CannotTell` needs no cell of its own: whatever stopped this question stopped
        # the lane's own one too, and `pr` is already saying `unknown`.
        return cell

    stacked = tuple(pr.number for pr in answer.pull_requests)
    numbers = ", ".join(f"#{number}" for number in stacked)
    return replace(cell, stacked=stacked, note=f"{cell.note} · base of {numbers}".strip(" ·"))


def _own_pr_cell(
    context: Context, lane: Lane, status: WorktreeStatus, remote_url: str | None
) -> PrCell:
    """What the `pr` column says: this branch's own pull requests, and nothing else."""
    try:
        answer = context.github.pull_request_for(
            branch=status.branch, remote_url=remote_url, cwd=lane.path
        )
    except Exception:
        return PrCell("unknown", "bad", "Could not ask GitHub about this branch.")

    match answer:
        case Found() as history:
            pr = history.decisive
            state = pr.state.lower()
            tone: Tone = "good" if pr.state == "MERGED" else "warn" if pr.state == "OPEN" else "bad"
            return PrCell(
                f"#{pr.number} {state}",
                tone,
                f"PR #{pr.number} {state} — {pr.url}{_earlier(history)}",
                merged=history.landed,
                after_merge=_after_merge(context, lane, history),
            )
        case NoPullRequest():
            return PrCell("none", "dim", "No pull request for this branch yet.")
        case CannotTell(remedy=remedy, detail=detail):
            # The one thing the close flow can never tell you, because for this
            # lane it refuses before it gets that far.
            return PrCell(
                "unknown", "bad", f"Pull request state unknown — {detail}. Fix with: {remedy}"
            )
        case NotApplicable(reason=reason):
            note = (
                "origin is not a GitHub remote, so there is no pull request to ask about."
                if reason == "not-github"
                else "This lane is on a detached HEAD, so there is no branch to have one."
            )
            return PrCell("—", "dim", note)


def _earlier(history: Found) -> str:
    """The branch's other pull requests, appended to the panel's one sentence.

    A line each would be silently sliced off: the panel keeps `MAX_DETAIL_LINES` and
    already spends them on the description, the branch and this sentence — so a lane
    with a history would lose exactly the part worth showing. Numbers and states only;
    the decisive one keeps the URL, and these share its prefix.
    """
    rest = [pr for pr in history.pull_requests if pr.number != history.decisive.number]
    if not rest:
        return ""
    return " · earlier: " + ", ".join(f"#{pr.number} {pr.state.lower()}" for pr in rest)


def _adds_something(description: str, name: str) -> bool:
    """Whether the description still says anything the lane name does not.

    A lane's name *is* its description, slugified — so `improve the export` and
    `improve-the-export` are one string rendered twice, and showing both is the
    fault this redesign set out to fix. It is only worth a line when the name could
    not keep everything: the forty-character cap cut it short, or transliteration
    replaced letters the user actually typed (`Login sayfası hatası`).

    Deliberately *not* `slugify(description) != name` — slugify is what produced
    the name, so that comparison suppresses exactly the accented spellings worth
    keeping. This asks the narrower question: is the name this description with its
    punctuation swapped for hyphens?
    """
    if not description:
        return False
    echo = re.sub(r"[^a-z0-9]+", "-", description.lower()).strip("-")
    return echo != name


def _detail(row: LaneRow) -> tuple[str, ...]:
    """The panel. **Only what has already been collected** — never a fresh call.

    That rule is what keeps it from being the close flow's diagnosis shown twice:
    which files are dirty and which commits are unpushed cost a git call per lane
    and stay where they change a decision.
    """
    lines: list[str] = []

    if _adds_something(row.lane.meta.description, row.lane.name):
        lines.append(row.lane.meta.description)

    if row.status is not None:
        lines.append(row.status.label)
    if row.pr.note:
        lines.append(row.pr.note)
    return tuple(lines)


def run(context: Context) -> None:
    ui = context.ui
    known: dict[str, PrCell] = {}
    cursor = 0
    table: Table | None = None

    while True:
        if table is None:
            lanes = context.lane_store().list_lanes()
            if not lanes:
                ui.detail("No open lanes. Open one from the menu.")
                return
            table = Table(context, lanes, known)
            ui.progress("Reading lane status…", table.collect)

        try:
            lane, cursor = ui.browse(
                table.title, COLUMNS, table.rows, back=BACK, fill=table.fill, cursor=cursor
            )
        except Abandoned:
            return

        try:
            verb = ui.choose(
                lane.slug,
                [
                    Choice("enter", "enter", "relaunch the editor in this lane"),
                    Choice("close", "close", "safety checks, then remove the worktree"),
                ],
            )
        except Abandoned:
            # Back out of the row menu and you are back at the table you were
            # looking at, not at the main menu: the table is a screen you are
            # standing in. This is the one place an action catches `Abandoned`, and
            # it is safe for the same reason as everywhere else — nothing
            # irreversible has happened yet. The table is *not* rebuilt: nothing
            # changed, so re-reading every lane's status would only flicker.
            continue

        if verb == "enter":
            enter_lane.enter(context, lane)
            # Your attention has moved to the editor. Holding the listing up would
            # imply there is more to do here, and its data is about to go stale.
            return

        # Imported here rather than at module scope: close_lane imports this
        # module's neighbours, and a top-level import would be circular.
        from lane.actions import close_lane

        try:
            close_lane.close(context, lane)
        except Abandoned:
            # Backing out of the close lands back at the table, for the same reason
            # as the row menu above: a close asks everything before it removes
            # anything, so an abandoned one has changed nothing. This also covers
            # Ctrl-C during its fetch, which would otherwise punish an impatient
            # keystroke by throwing away the screen it happened on.
            continue
        # And stay: closing several lanes in a row is a real batch. The table is
        # rebuilt because a row has gone, but the pull request answers already paid
        # for are kept, so the second paint is immediate.
        table = None

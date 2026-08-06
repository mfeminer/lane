"""Close a lane: check, confirm everything, then remove.

The shape of this action is the important part. It runs its checks, reports what it
found, asks **every** question it needs — including permission to force-delete an
unmerged branch and whether to rescue stranded commits — and only then touches
disk. Backing out at any prompt changes nothing, so there is no rollback logic.

The pull request check exists because git's ancestry check reports a false negative
for a squashed or rebased merge: the lane's commits never literally appear in the
default branch. A `MERGED` pull request therefore counts as clean even when git
disagrees. That is the whole reason this feature is here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lane import interrupts
from lane.actions.picking import resolve_base
from lane.context import Context
from lane.git.backend import GitError, WorktreeStatus
from lane.github.client import (
    CannotTell,
    Found,
    NoPullRequest,
    NotApplicable,
    PrLookup,
    PullRequest,
)
from lane.lanes import Lane


@dataclass
class _Findings:
    """What the checks turned up, before anything is asked."""

    issues: list[str] = field(default_factory=list)
    clean_notes: list[str] = field(default_factory=list)

    history: list[str] = field(default_factory=list)
    """The branch's other pull requests: neither reassurance nor blocker.

    A lane's branch can carry several over its life, and only one of them decides
    whether it can close. Reporting the rest as clean notes would tick a `✓` beside a
    pull request that was closed without merging; reporting them as issues would
    invent a blocker out of history. They get their own quiet tone instead.
    """

    pr_merged: bool = False

    @property
    def blocking(self) -> int:
        return len(self.issues)


@dataclass
class _Decisions:
    """Everything the user agreed to, gathered before the first removal."""

    proceed: bool = False
    rescue_branch: str | None = None
    force_delete_branch: bool = False
    delete_branch: bool = False

    also_delete: tuple[str, ...] = ()
    """The lane's other branches — the ones it moved through before this one."""

    force_delete_others: bool = False
    """Permission to force-delete those of them that hold unique work."""


def close(context: Context, lane: Lane) -> None:
    """Close a lane the listing has already put the cursor on.

    It takes the lane rather than asking for one: closing is reached from the
    listing, which is a better place to choose a lane than a picker that shows the
    same names with none of the status (ADR 0002).
    """
    ui = context.ui

    base = resolve_base(context, lane)
    if base is None:
        ui.error("Could not determine the default branch, so the checks cannot run.")
        ui.detail("  Try: git remote set-head origin --auto")
        return

    repo = lane.repo_path(context.projects_root)

    ui.heading(f"Closing {lane.slug}")
    ui.detail(f"  {lane.description()}")

    fetch = ui.progress("Fetching origin…", lambda: context.git.fetch_prune(repo))
    if not fetch.ok:
        ui.warn("Fetch failed (offline?) — merge state may be stale.")

    try:
        status = context.git.status(lane.path, base, lane.meta.start)
    except GitError as exc:
        ui.error(f"Could not inspect the lane: {exc}")
        return

    remote_url = context.git.remote_url(repo)
    answer = ui.progress(
        "Asking GitHub about the pull request…",
        lambda: context.github.pull_request_for(
            branch=status.branch, remote_url=remote_url, cwd=lane.path
        ),
    )

    # A lane that cannot be checked is refused — decided from the client's answer
    # alone, never by probing the environment separately.
    if isinstance(answer, CannotTell):
        ui.blank()
        ui.error(f"Cannot verify the pull request for '{status.branch}': {answer.detail}.")
        ui.detail(f"  Fix it with: {answer.remedy}")
        ui.detail("  Then close this lane again.")
        return

    findings = _check(context, lane, status, base, answer)
    _report(context, findings)

    decisions = _ask(context, lane, status, base, findings)
    if not decisions.proceed:
        ui.info("Left open.")
        return

    _execute(context, lane, repo, status, decisions)


def _check(
    context: Context,
    lane: Lane,
    status: WorktreeStatus,
    base: str,
    answer: PrLookup,
) -> _Findings:
    findings = _Findings()

    # 1) uncommitted or untracked files
    if status.dirty_count > 0:
        findings.issues.append(
            f"{status.dirty_count} uncommitted or untracked file(s) in this lane"
        )
    else:
        findings.clean_notes.append("Working tree is clean.")

    # 2) unpushed commits. What the count *means* depends on the pull request answer.
    # With no upstream there is no remote to measure against, so the count falls back
    # to `origin/<base>` — where a squash merge left none of the lane's commits. That
    # is the same false negative check 3 exists to correct, and reading it as "never
    # pushed" reported `✓ PR merged` and `! never pushed` about one lane.
    landed = _landed_by(answer)
    if status.unpushed_count == 0:
        findings.clean_notes.append("Nothing left to push.")
    elif status.upstream is not None:
        # A live upstream makes this a real measurement against a real remote branch.
        findings.issues.append(
            f"{status.unpushed_count} commit(s) not pushed (ahead of {status.upstream})"
        )
    elif landed is not None:
        _check_against_the_merge(context, lane, status, findings, landed)
    elif status.pushed_before:
        # Pushed once, its remote branch since deleted, and nothing merged — so the
        # commits are real and there is nowhere they currently live.
        findings.issues.append(
            f"{status.unpushed_count} commit(s) not in origin/{base}, and the remote "
            f"branch they were pushed to is gone"
        )
    else:
        findings.issues.append(
            f"Branch was never pushed — {status.unpushed_count} commit(s) on top of origin/{base}"
        )

    # 3) has the work reached origin/<base>?
    #
    # Reported before anything below decides, and whichever way it decides: the rest of
    # the branch's pull requests are how the user recognises the lane in front of them,
    # and every `return` here would otherwise drop them.
    _note_the_rest_of_the_history(findings, answer)

    if status.merged and not status.has_own_commits:
        # Nothing was ever committed here, so "every commit is in origin/<base>" is
        # true only vacuously — and reads as reassurance the user has not earned.
        findings.clean_notes.append("This lane has no commits of its own — nothing to merge.")
        return findings

    if status.merged:
        findings.clean_notes.append(f"Every commit is in origin/{base}.")
        if isinstance(answer, Found) and answer.landed:
            findings.pr_merged = True
        return findings

    match answer:
        case Found() as history if history.landed:
            # The false negative this feature exists to resolve.
            pr = history.decisive
            findings.pr_merged = True
            findings.clean_notes.append(
                f"PR #{pr.number} is merged (squashed or rebased, which is why "
                f"git's ancestry check disagrees) — {pr.url}"
            )
        case Found(decisive=pr) if pr.state == "OPEN":
            # Reached even when an earlier one merged: an open pull request is work
            # that has not landed, and closing the lane takes the branch it is on.
            findings.issues.append(f"PR #{pr.number} is still open — {pr.url}")
        case Found(decisive=pr):
            findings.issues.append(f"PR #{pr.number} was closed without being merged — {pr.url}")
        case NoPullRequest():
            findings.issues.append(
                f"Not merged into origin/{base}, and no pull request exists for this branch"
            )
        case NotApplicable(reason=reason):
            note = (
                "origin is not a GitHub remote"
                if reason == "not-github"
                else "this lane is on a detached HEAD"
            )
            findings.issues.append(
                f"Not merged into origin/{base} (pull request check skipped: {note})"
            )
        case _:  # pragma: no cover - CannotTell is handled before this point
            findings.issues.append(f"Not merged into origin/{base}")

    return findings


def _note_the_rest_of_the_history(findings: _Findings, answer: PrLookup) -> None:
    """Every pull request except the one the close turns on.

    `gh pr view <branch>` used to answer with the most relevant pull request, which
    made a branch's history invisible: an earlier one merging left nothing on screen
    to say so. These lines are that history, and they are never a verdict.
    """
    if not isinstance(answer, Found):
        return

    decisive = answer.decisive
    for pr in answer.pull_requests:
        if pr.number == decisive.number:
            continue
        findings.history.append(f"PR #{pr.number} {pr.state.lower()} — {pr.url}")


def _landed_by(answer: PrLookup) -> PullRequest | None:
    """The pull request that put this lane's work in the base, if one did.

    None when a follow-up is still open: `Found.landed` is deliberately not "any of
    them merged", because a lane with work in flight has not landed it.
    """
    return answer.decisive if isinstance(answer, Found) and answer.landed else None


def _check_against_the_merge(
    context: Context,
    lane: Lane,
    status: WorktreeStatus,
    findings: _Findings,
    pr: PullRequest,
) -> None:
    """Which of these commits the pull request carried, and which came after it.

    Counting from the commit the pull request's head was at is the only way to tell:
    a squash merge puts none of them in the base, so ancestry cannot separate work
    that landed from work done afterwards, and the two mean opposite things here.
    """
    since = context.git.commits_since(lane.path, pr.head_oid)

    if since is None:
        # The commit it merged from is not on this branch any more, so how much of
        # this work landed is unknowable from here. Refused, exactly as an
        # unanswerable `gh` is — the close decides on this answer.
        findings.issues.append(
            f"Cannot tell what PR #{pr.number} carried — the commit it merged from is "
            f"not on this branch any more (amended or rebased since)"
        )
    elif since == 0:
        gone = " and its remote branch went with it" if status.pushed_before else ""
        findings.clean_notes.append(
            f"Nothing left to push — PR #{pr.number} carried all "
            f"{status.unpushed_count} commit(s){gone}."
        )
    else:
        # These exist in this worktree and nowhere else — a merged pull request is no
        # amnesty for work committed after it.
        findings.issues.append(
            f"{since} commit(s) made after PR #{pr.number} merged, and never pushed"
        )


def _report(context: Context, findings: _Findings) -> None:
    ui = context.ui
    ui.blank()
    for note in findings.clean_notes:
        ui.ok(note)
    # Between the two, so the branch's pull requests read in order: what landed, then
    # what is still in the way.
    for line in findings.history:
        ui.detail(f"  {line}")
    for issue in findings.issues:
        ui.warn(issue)


def _ask(
    context: Context,
    lane: Lane,
    status: WorktreeStatus,
    base: str,
    findings: _Findings,
) -> _Decisions:
    """Every question, in one pass, before anything is removed."""
    ui = context.ui
    decisions = _Decisions()

    # Whether the local branch goes too, decided before anything is said, so the
    # summary can state it rather than leaving the user to discover it afterwards.
    # Whether deleting the branch could lose anything. Plain ancestry, not
    # `status.landed`: a lane that never committed is an ancestor of its base, so its
    # branch holds nothing unique and deleting it is trivially safe — even though
    # nothing "landed". The pull request covers the squash case, where the commits
    # are real but exist nowhere in the base.
    nothing_would_be_lost = status.merged or findings.pr_merged
    deletes_branch = status.branch is not None and status.branch != base

    # Read now, while the worktree is still there to read it from: `git worktree
    # remove` takes the reflog these come from with it, and every question about them
    # has to be asked before anything is touched anyway.
    decisions.also_delete = _other_lane_branches(context, lane, status, base)

    # Which of them git will refuse to delete, asked now so the summary can mark them
    # rather than leaving the user to find out from a warning after the fact.
    repo = lane.repo_path(context.projects_root)
    unmerged_others = tuple(
        other for other in decisions.also_delete if not context.git.branch_merged(repo, other, base)
    )

    # What is about to be removed, spelled out before the destructive step.
    ui.blank()
    ui.heading("About to remove")
    ui.info(f"  Worktree : {lane.path}")
    if status.branch is None:
        ui.info("  Branch   : none (detached)")
    elif not deletes_branch:
        ui.info(f"  Branch   : {status.branch} (kept — it is the base branch)")
    elif nothing_would_be_lost:
        ui.info(f"  Branch   : {status.branch} — will be deleted")
    else:
        ui.warn(f"  Branch   : {status.branch} — will be deleted, and it is not merged")
    for other in decisions.also_delete:
        earlier = "this lane used it earlier"
        if other in unmerged_others:
            ui.warn(f"  Branch   : {other} — not merged, {earlier}")
        else:
            ui.info(f"  Branch   : {other} — will be deleted ({earlier})")
    if status.dirty_count > 0:
        ui.warn(f"  Closing now discards {status.dirty_count} uncommitted file(s) for good.")

    ui.blank()
    if findings.blocking:
        count = findings.blocking
        ui.warn(f"{count} issue{'s' if count != 1 else ''} holding this lane open.")
        decisions.proceed = ui.confirm("Close it anyway?")
    else:
        ui.ok("Lane is clear.")
        decisions.proceed = ui.confirm("Close it?")

    if not decisions.proceed:
        return decisions

    # Commits on a detached HEAD become unreachable once the worktree is gone, so
    # the offer to park them must come before the removal, not after.
    if status.detached and status.unpushed_count > 0:
        ui.blank()
        ui.warn(
            f"{status.unpushed_count} commit(s) sit on a detached HEAD and become "
            "unreachable once this lane closes."
        )
        rescue = f"wip/{lane.name}"
        if ui.confirm(f"Park them on a branch called '{rescue}'?", default=True):
            decisions.rescue_branch = rescue

    # A lane's branch goes with the lane — leaving it behind is how a repository
    # fills up with dead branches after every successful close.
    #
    # Permission to force-delete is asked here rather than after the worktree is
    # gone, so that declining leaves everything as it was.
    if deletes_branch:
        decisions.delete_branch = True
        if nothing_would_be_lost:
            # `-d` may still refuse — a squash or rebase merge leaves the commits
            # nowhere in the base, which is the whole reason the pull request was
            # consulted. Forcing is then correct rather than dangerous, and needs no
            # second question: the summary already said the branch would go.
            decisions.force_delete_branch = True
        else:
            ui.blank()
            decisions.force_delete_branch = ui.confirm(
                f"Branch '{status.branch}' is not merged. Delete it anyway?"
            )

    # The same permission, for the branches this lane used before the one it is on.
    # One question for all of them: they share a reason and a fate, and a prompt per
    # branch would turn closing a lane that moved around into an interrogation.
    if unmerged_others:
        ui.blank()
        decisions.force_delete_others = ui.confirm(_unmerged_others_question(unmerged_others))

    return decisions


def _unmerged_others_question(unmerged: tuple[str, ...]) -> str:
    """Worded like the current branch's question, because it is the same question."""
    if len(unmerged) == 1:
        return f"Branch '{unmerged[0]}' is not merged. Delete it anyway?"
    return (
        f"{len(unmerged)} branches this lane used are not merged "
        f"({', '.join(unmerged)}). Delete them anyway?"
    )


def _other_lane_branches(
    context: Context, lane: Lane, status: WorktreeStatus, base: str
) -> tuple[str, ...]:
    """The lane's branches apart from the one it is standing on.

    A lane is one task, and a task can move through several branches — lane is not
    watching while it does, so the worktree's reflog is the only record of them. The
    base branch is never one of them, however often it was visited.
    """
    try:
        used = context.git.branches_used(lane.path)
    except GitError:
        # A lane whose branches cannot be listed still closes; the one it is on is
        # known from `status` either way.
        return ()
    return tuple(name for name in used if name not in (status.branch, base))


def _execute(
    context: Context,
    lane: Lane,
    repo: Path,
    status: WorktreeStatus,
    decisions: _Decisions,
) -> None:
    """Nothing here asks anything. Every decision was made above.

    Every step announces itself. This is the slow half of a close — removing a
    worktree of a few thousand files takes far longer than any check that ran before
    it — and it is also the half that runs *after* the last question, so a silent
    pause here reads as a hang rather than as work.

    It is also the one stretch of lane where Ctrl-C is deferred rather than obeyed
    at once. Everywhere else stopping is a clean no-op because every question came
    first; here there is nothing left to abandon and plenty to leave half-done, and
    a lane whose worktree is gone but whose branch and metadata survive is a state
    nothing in lane can describe. So the whole phase runs, and the interrupt is
    raised after it.
    """
    ui = context.ui

    def acknowledge() -> None:
        ui.detail("  Ctrl-C received — finishing the removal first. Ctrl-C again to stop now.")

    with interrupts.deferred(acknowledge):
        _remove_everything(context, lane, repo, status, decisions)


def _remove_everything(
    context: Context,
    lane: Lane,
    repo: Path,
    status: WorktreeStatus,
    decisions: _Decisions,
) -> None:
    """The destructive phase itself, run under the deferral above."""
    ui = context.ui

    rescue = decisions.rescue_branch
    if rescue is not None:
        try:
            head = context.git.head_commit(lane.path)
            ui.progress(
                f"Parking the commits on {rescue}…",
                lambda: context.git.create_branch(repo, rescue, head),
            )
        except GitError as exc:
            ui.error(f"Could not park the commits: {exc}")
            ui.warn("Leaving the lane open so nothing is lost.")
            return
        ui.ok(f"Parked on {rescue}")

    def remove() -> None:
        # The user has just confirmed, which is the only thing that justifies
        # --force here; git's refusal is the safety net everywhere else.
        context.git.remove_worktree(repo, lane.path, force=True)
        # Pruning is bookkeeping belonging to the removal rather than a step of its
        # own, so it shares the one spinner: one spinner per user-visible action.
        context.git.prune_worktrees(repo)

    try:
        ui.progress("Removing the worktree…", remove)
    except GitError as exc:
        ui.error(f"Could not remove the worktree: {exc}")
        return
    context.lane_store().forget(lane.project, lane.name)
    ui.ok(f"Lane closed: {lane.slug}")

    # A detached lane has no branch of its own to delete, and a wip/ branch created by
    # the rescue above is never deleted — that would defeat its purpose.
    if decisions.delete_branch and status.branch is not None:
        _delete_branch(context, repo, status.branch, may_force=decisions.force_delete_branch)
    for other in decisions.also_delete:
        _delete_branch(context, repo, other, may_force=decisions.force_delete_others)


def _delete_branch(context: Context, repo: Path, branch: str, *, may_force: bool) -> None:
    """One branch, announced, and reported either way."""
    ui = context.ui

    def delete() -> bool:
        # `-d` first, so git's own merged check gets the chance to object. When the
        # work landed as a squash or rebase merge it will object, and forcing is then
        # correct rather than dangerous — the user was told in the summary either
        # way, so both paths report the same thing.
        if context.git.delete_branch(repo, branch):
            return True
        return may_force and context.git.delete_branch(repo, branch, force=True)

    if ui.progress(f"Deleting the branch {branch}…", delete):
        ui.ok(f"Branch deleted: {branch}")
        return

    ui.warn(f"Branch kept: {branch}")
    ui.detail(f"  Delete it yourself with: git -C {repo} branch -D {branch}")

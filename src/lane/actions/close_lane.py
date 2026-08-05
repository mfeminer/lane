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

from lane.actions.picking import resolve_base
from lane.context import Context
from lane.git.backend import GitError, WorktreeStatus
from lane.github.client import CannotTell, Found, NoPullRequest, NotApplicable, PrLookup
from lane.lanes import Lane


@dataclass
class _Findings:
    """What the checks turned up, before anything is asked."""

    issues: list[str] = field(default_factory=list)
    clean_notes: list[str] = field(default_factory=list)
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

    # 2) unpushed commits
    if status.unpushed_count > 0:
        if status.upstream is not None:
            findings.issues.append(
                f"{status.unpushed_count} commit(s) not pushed (ahead of {status.upstream})"
            )
        else:
            findings.issues.append(
                f"Branch was never pushed — {status.unpushed_count} commit(s) "
                f"on top of origin/{base}"
            )
    else:
        findings.clean_notes.append("Nothing left to push.")

    # 3) has the work reached origin/<base>?
    if status.merged and not status.has_own_commits:
        # Nothing was ever committed here, so "every commit is in origin/<base>" is
        # true only vacuously — and reads as reassurance the user has not earned.
        findings.clean_notes.append("This lane has no commits of its own — nothing to merge.")
        return findings

    if status.merged:
        findings.clean_notes.append(f"Every commit is in origin/{base}.")
        if isinstance(answer, Found) and answer.pull_request.state == "MERGED":
            findings.pr_merged = True
        return findings

    match answer:
        case Found(pull_request=pr) if pr.state == "MERGED":
            # The false negative this feature exists to resolve.
            findings.pr_merged = True
            findings.clean_notes.append(
                f"PR #{pr.number} is merged (squashed or rebased, which is why "
                f"git's ancestry check disagrees) — {pr.url}"
            )
        case Found(pull_request=pr) if pr.state == "OPEN":
            findings.issues.append(f"PR #{pr.number} is still open — {pr.url}")
        case Found(pull_request=pr):
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

    del context, lane
    return findings


def _report(context: Context, findings: _Findings) -> None:
    ui = context.ui
    ui.blank()
    for note in findings.clean_notes:
        ui.ok(note)
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

    return decisions


def _execute(
    context: Context,
    lane: Lane,
    repo: Path,
    status: WorktreeStatus,
    decisions: _Decisions,
) -> None:
    """Nothing here asks anything. Every decision was made above."""
    ui = context.ui

    if decisions.rescue_branch is not None:
        try:
            head = context.git.head_commit(lane.path)
            context.git.create_branch(repo, decisions.rescue_branch, head)
        except GitError as exc:
            ui.error(f"Could not park the commits: {exc}")
            ui.warn("Leaving the lane open so nothing is lost.")
            return
        ui.ok(f"Parked on {decisions.rescue_branch}")

    try:
        # The user has just confirmed, which is the only thing that justifies
        # --force here; git's refusal is the safety net everywhere else.
        context.git.remove_worktree(repo, lane.path, force=True)
    except GitError as exc:
        ui.error(f"Could not remove the worktree: {exc}")
        return
    context.git.prune_worktrees(repo)
    context.lane_store().forget(lane.project, lane.name)
    ui.ok(f"Lane closed: {lane.slug}")

    if not decisions.delete_branch or status.branch is None:
        # A detached lane has no branch to delete, and a wip/ branch created by the
        # rescue is never deleted — that would defeat its purpose.
        return

    # `-d` first, so git's own merged check gets the chance to object. When the work
    # landed as a squash or rebase merge it will object, and forcing is then correct
    # rather than dangerous — the user was told in the summary either way, so both
    # paths report the same thing.
    if context.git.delete_branch(repo, status.branch):
        ui.ok(f"Branch deleted: {status.branch}")
        return

    if decisions.force_delete_branch and context.git.delete_branch(repo, status.branch, force=True):
        ui.ok(f"Branch deleted: {status.branch}")
        return

    ui.warn(f"Branch kept: {status.branch}")
    ui.detail(f"  Delete it yourself with: git -C {repo} branch -D {status.branch}")

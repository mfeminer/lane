"""The `GitHubClient` seam: one real question, with "I cannot tell you" as an answer.

The question is *what pull requests has this branch had*, plural: a branch can carry
a history of them — one merged, a follow-up open — and answering with only the most
recent silently drops the rest. The close path decides from the answer alone and
never probes the environment separately — that is what lets a single stub in the
tests control the behaviour completely.

Today the implementation shells out to `gh`. Tomorrow it might be an HTTP call, and
the rest of the application must not be able to tell.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

type PrState = Literal["OPEN", "CLOSED", "MERGED"]
type CannotTellReason = Literal["gh-missing", "gh-logged-out", "gh-failed"]
type NotApplicableReason = Literal["not-github", "detached"]


@dataclass(frozen=True, slots=True)
class PullRequest:
    number: int
    state: PrState
    url: str

    head_oid: str = ""
    """The commit this pull request's head was at.

    How the close path tells commits that landed from commits made after the merge:
    a squash merge leaves the branch's commits nowhere in the base, so counting from
    here is the only way to know which of them the pull request actually carried.
    """


@dataclass(frozen=True, slots=True)
class Found:
    """Every pull request whose head was this branch, newest number first.

    Never empty: "there are none" is `NoPullRequest`, so every reader can ask which of
    them is `decisive` without checking first.
    """

    pull_requests: tuple[PullRequest, ...]

    @property
    def decisive(self) -> PullRequest:
        """The one the lane's state turns on.

        An open pull request is work that has not landed, so it decides even when a
        newer one has already merged — the listing's question is *can I close this*,
        and an open one is the answer whatever its age. Failing that, the newest
        merged one; failing that, the newest there is.
        """
        for state in ("OPEN", "MERGED"):
            for pr in self.pull_requests:
                if pr.state == state:
                    return pr
        return self.pull_requests[0]

    @property
    def landed(self) -> bool:
        """GitHub says this lane's work is in the base branch.

        Deliberately *not* "any of them merged": with a follow-up still open the lane
        holds work that has not landed, and the squash-merge correction this answer
        exists for would then excuse commits nothing has taken.
        """
        return self.decisive.state == "MERGED"


@dataclass(frozen=True, slots=True)
class NoPullRequest:
    """GitHub was asked and has no pull request for this branch."""


@dataclass(frozen=True, slots=True)
class CannotTell:
    """The question could not be answered — a first-class result, not an error.

    `remedy` is the exact command that fixes it, so the close path can quote it
    without knowing why it failed.
    """

    reason: CannotTellReason
    remedy: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class NotApplicable:
    """There is no pull request to ask about, so the close proceeds on git's evidence."""

    reason: NotApplicableReason


type PrLookup = Found | NoPullRequest | CannotTell | NotApplicable


def found(*pull_requests: PullRequest) -> Found:
    """The one way to build a `Found`, so *newest first* is true wherever it is read.

    Sorting here rather than trusting the order they arrived in: `gh` sorts by its
    own notion of recency, and the callers that want the decisive pull request would
    otherwise each have to re-establish which one that is.
    """
    return Found(tuple(sorted(pull_requests, key=lambda pr: pr.number, reverse=True)))


def not_applicable(reason: NotApplicableReason) -> NotApplicable:
    return NotApplicable(reason)


class GitHubClient(Protocol):
    def pull_request_for(
        self, *, branch: str | None, remote_url: str | None, cwd: Path
    ) -> PrLookup:
        """The pull request state for `branch`.

        `branch` is None for a detached lane and `remote_url` is whatever origin
        points at — the caller passes what it already knows so that this seam,
        and only this seam, decides whether `gh` is worth invoking.
        """
        ...


def is_github_remote(remote_url: str | None) -> bool:
    return remote_url is not None and "github.com" in remote_url

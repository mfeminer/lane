"""The `GitHubClient` seam: one real question, with "I cannot tell you" as an answer.

The question is *what is the state of the pull request for this branch*. The close
path decides from the answer alone and never probes the environment separately —
that is what lets a single stub in the tests control the behaviour completely.

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


@dataclass(frozen=True, slots=True)
class Found:
    """There is a pull request, and this is its state."""

    pull_request: PullRequest


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

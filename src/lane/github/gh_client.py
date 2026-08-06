"""The `gh` implementation of `GitHubClient`. The only place `gh` is spawned.

`gh` is a settled dependency — see AGENTS.md for why (there is no official GitHub
SDK for Python, and taking on a third-party one would mean owning token storage and
keychain handling for a single API call).

It is enforced *here*, where it is used, and never at startup. Everything else in
lane works without it, including closing a lane whose remote is not GitHub.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from lane.github.client import (
    CannotTell,
    DependentLookup,
    Dependents,
    NoPullRequest,
    NotApplicable,
    PrLookup,
    PrState,
    PullRequest,
    found,
    is_github_remote,
)

_TIMEOUT = 60

_LIMIT = 100
"""How many pull requests one branch could plausibly have had. `gh` defaults to 30
and says nothing when it truncates, and silently dropping history is the fault this
query exists to fix."""

INSTALL_REMEDY = "brew install gh"
LOGIN_REMEDY = "gh auth login"

_VALID_STATES: tuple[PrState, ...] = ("OPEN", "CLOSED", "MERGED")


class GhClient:
    """Asks GitHub, via `gh`, what the pull request for a branch is doing."""

    def __init__(self, gh_command: str = "gh") -> None:
        self._gh = gh_command

    def pull_request_for(
        self, *, branch: str | None, remote_url: str | None, cwd: Path
    ) -> PrLookup:
        listed = self._list(
            branch=branch,
            remote_url=remote_url,
            cwd=cwd,
            select=("--head", "--state", "all"),
            fields="number,state,url,headRefOid",
        )
        if not isinstance(listed, str):
            return listed
        return self._parse(listed)

    def pull_requests_based_on(
        self, *, branch: str | None, remote_url: str | None, cwd: Path
    ) -> DependentLookup:
        # Only open ones: a closed or merged pull request based on this branch is no
        # longer at risk from deleting it.
        listed = self._list(
            branch=branch,
            remote_url=remote_url,
            cwd=cwd,
            select=("--base", "--state", "open"),
            fields="number,state,url",
        )
        if not isinstance(listed, str):
            return listed
        return self._parse_dependents(listed)

    def _list(
        self,
        *,
        branch: str | None,
        remote_url: str | None,
        cwd: Path,
        select: tuple[str, str, str],
        fields: str,
    ) -> str | CannotTell | NotApplicable:
        """Run one `gh pr list`, returning its stdout or the reason there is none.

        Both questions are the same subprocess with a different filter, and both have
        the same three ways of not being answerable. Sharing this is what keeps "I
        cannot tell you" identical for either of them rather than nearly identical.
        """
        # Both of these are answered without invoking `gh` at all: there is no pull
        # request to ask about, so the close proceeds on git's own evidence.
        if branch is None:
            return NotApplicable("detached")
        if not is_github_remote(remote_url):
            return NotApplicable("not-github")

        which, state_flag, state = select
        try:
            done = subprocess.run(
                [
                    self._gh,
                    "pr",
                    "list",
                    which,
                    branch,
                    state_flag,
                    state,
                    "--limit",
                    str(_LIMIT),
                    "--json",
                    fields,
                ],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
                check=False,
            )
        except FileNotFoundError:
            return CannotTell(
                reason="gh-missing",
                remedy=INSTALL_REMEDY,
                detail="the GitHub CLI is not installed",
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return CannotTell(
                reason="gh-failed",
                remedy=LOGIN_REMEDY,
                detail=f"gh could not be run: {exc}",
            )

        if done.returncode != 0:
            failure = self._interpret_failure(done.stderr)
            # `no pull requests found` is `gh` being chatty about an empty result, and
            # for either question an empty result is stdout's business, not an error.
            return failure if isinstance(failure, CannotTell) else ""

        return done.stdout

    def _interpret_failure(self, stderr: str) -> PrLookup:
        """`gh` uses one exit code for many situations, so the message decides."""
        lowered = stderr.lower()

        if "no pull requests found" in lowered or "no pull request found" in lowered:
            return NoPullRequest()

        if any(
            hint in lowered
            for hint in (
                "authentication",
                "not logged",
                "gh auth login",
                "no accounts",
                "requires authentication",
                "bad credentials",
            )
        ):
            return CannotTell(
                reason="gh-logged-out",
                remedy=LOGIN_REMEDY,
                detail="gh is installed but not logged in",
            )

        # Anything else — a network failure, a repository gh cannot resolve — is
        # still "I cannot tell you", never a silent pass.
        return CannotTell(
            reason="gh-failed",
            remedy=LOGIN_REMEDY,
            detail=stderr.strip().splitlines()[0] if stderr.strip() else "gh failed",
        )

    def _parse(self, stdout: str) -> PrLookup:
        if not stdout.strip():
            return NoPullRequest()
        try:
            body = json.loads(stdout)
        except json.JSONDecodeError as exc:
            return CannotTell(
                reason="gh-failed",
                remedy=LOGIN_REMEDY,
                detail=f"gh returned something unreadable: {exc}",
            )
        # `gh pr list` answers with an array, and an empty one is the ordinary way it
        # says there are none — not a failure.
        if not isinstance(body, list):
            return NoPullRequest()

        pull_requests = [pr for pr in (self._one(item) for item in body) if pr is not None]
        if not pull_requests:
            # `[]` is how `gh pr list` says there are none, and it is a `NoPullRequest`
            # rather than an empty `Found` — which would have no decisive pull request
            # for its readers to ask about.
            return NoPullRequest()

        return found(*pull_requests)

    def _parse_dependents(self, stdout: str) -> DependentLookup:
        """Empty is a real answer here, so there is no `NoPullRequest` to fall back to."""
        if not stdout.strip():
            return Dependents(())
        try:
            body = json.loads(stdout)
        except json.JSONDecodeError as exc:
            return CannotTell(
                reason="gh-failed",
                remedy=LOGIN_REMEDY,
                detail=f"gh returned something unreadable: {exc}",
            )
        if not isinstance(body, list):
            return Dependents(())

        return Dependents(tuple(pr for pr in (self._one(item) for item in body) if pr is not None))

    def _one(self, item: object) -> PullRequest | None:
        """One entry, or None when it carries nothing that identifies a pull request."""
        if not isinstance(item, dict):
            return None

        raw_state = str(item.get("state", "")).upper()
        state: PrState = raw_state if raw_state in _VALID_STATES else "OPEN"
        try:
            number = int(item.get("number", 0))
        except TypeError, ValueError:
            number = 0
        url = str(item.get("url", ""))

        if number == 0 and not url:
            return None

        return PullRequest(
            number=number, state=state, url=url, head_oid=str(item.get("headRefOid", ""))
        )

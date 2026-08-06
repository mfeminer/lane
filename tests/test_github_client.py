"""The GitHub client, and the state file.

The suite never authenticates or reaches the network: `gh` is replaced by a script
on PATH that prints what a real `gh` would.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from lane.github.client import (
    CannotTell,
    Dependents,
    Found,
    NoPullRequest,
    NotApplicable,
    PrState,
    PullRequest,
    found,
)
from lane.github.gh_client import GhClient
from lane.state import State, StateStore


def _fake_gh(tmp_path: Path, *, stdout: str = "", stderr: str = "", code: int = 0) -> str:
    """A stand-in `gh` on disk. Never contacts GitHub."""
    script = tmp_path / "fake-gh"
    script.write_text(
        f"#!/bin/sh\ncat <<'OUT'\n{stdout}\nOUT\ncat >&2 <<'ERR'\n{stderr}\nERR\nexit {code}\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


GITHUB = "git@github.com:acme/thing.git"


# -- G1, G2: the one real question ------------------------------------------------


def test_a_merged_pull_request_is_reported_with_its_number_and_url(tmp_path: Path) -> None:
    gh = _fake_gh(
        tmp_path,
        stdout=(
            '[{"number": 42, "state": "MERGED",'
            ' "url": "https://github.com/acme/thing/pull/42", "headRefOid": "c0ffee"}]'
        ),
    )

    answer = GhClient(gh).pull_request_for(branch="feature/x", remote_url=GITHUB, cwd=tmp_path)

    assert isinstance(answer, Found)
    assert len(answer.pull_requests) == 1
    assert answer.pull_requests[0].number == 42
    assert answer.pull_requests[0].state == "MERGED"
    assert answer.pull_requests[0].url.endswith("/pull/42")
    assert answer.pull_requests[0].head_oid == "c0ffee"


def test_every_pull_request_for_the_branch_is_carried_newest_first(tmp_path: Path) -> None:
    """A branch can have a history of pull requests, and none of it is dropped.

    The order is ours, not `gh`'s: the newest number first, whatever came back.
    """
    gh = _fake_gh(
        tmp_path,
        stdout=(
            '[{"number": 41, "state": "MERGED", "url": "u41", "headRefOid": "aaa"},'
            ' {"number": 42, "state": "OPEN", "url": "u42", "headRefOid": "bbb"}]'
        ),
    )

    answer = GhClient(gh).pull_request_for(branch="feature/x", remote_url=GITHUB, cwd=tmp_path)

    assert isinstance(answer, Found)
    assert [pr.number for pr in answer.pull_requests] == [42, 41]
    assert [pr.state for pr in answer.pull_requests] == ["OPEN", "MERGED"]


@pytest.mark.parametrize("state", ["OPEN", "CLOSED", "MERGED"])
def test_every_pull_request_state_is_carried_through(tmp_path: Path, state: str) -> None:
    gh = _fake_gh(tmp_path, stdout=f'[{{"number": 7, "state": "{state}", "url": "u"}}]')

    answer = GhClient(gh).pull_request_for(branch="b", remote_url=GITHUB, cwd=tmp_path)

    assert isinstance(answer, Found)
    assert answer.pull_requests[0].state == state


def test_an_empty_list_is_how_gh_says_there_are_none(tmp_path: Path) -> None:
    """`gh pr list` succeeds and answers `[]` — the ordinary no-pull-request case now.

    It is not an error and not something the caller should have to recognise: `none`
    and `unknown` are different answers everywhere else in lane, and this is the one
    that means `none`.
    """
    gh = _fake_gh(tmp_path, stdout="[]")

    answer = GhClient(gh).pull_request_for(branch="feature/x", remote_url=GITHUB, cwd=tmp_path)

    assert isinstance(answer, NoPullRequest)


def test_no_pull_request_found(tmp_path: Path) -> None:
    gh = _fake_gh(
        tmp_path,
        stderr='no pull requests found for branch "feature/x"',
        code=1,
    )

    answer = GhClient(gh).pull_request_for(branch="feature/x", remote_url=GITHUB, cwd=tmp_path)

    assert isinstance(answer, NoPullRequest)


# -- what is stacked on top of this branch ----------------------------------------


def test_pull_requests_based_on_this_branch_are_a_separate_question(tmp_path: Path) -> None:
    """`--head` and `--base` are opposite ends of one relationship.

    The first asks what this branch produced, and answers whether the lane's work
    landed. Only the second says *deleting this branch would break somebody's pull
    request*, which is a fact about the close, not about the work.
    """
    gh = _fake_gh(
        tmp_path,
        stdout='[{"number": 99, "state": "OPEN", "url": "https://github.com/a/b/pull/99"}]',
    )

    answer = GhClient(gh).pull_requests_based_on(
        branch="feature/x", remote_url=GITHUB, cwd=tmp_path
    )

    assert isinstance(answer, Dependents)
    assert [pr.number for pr in answer.pull_requests] == [99]
    assert answer.pull_requests[0].url.endswith("/pull/99")


def test_nothing_based_on_this_branch_is_none_rather_than_a_failure(tmp_path: Path) -> None:
    """The ordinary case, and the one that must not read as "I could not ask"."""
    gh = _fake_gh(tmp_path, stdout="[]")

    answer = GhClient(gh).pull_requests_based_on(
        branch="feature/x", remote_url=GITHUB, cwd=tmp_path
    )

    assert isinstance(answer, Dependents)
    assert answer.pull_requests == ()


def test_dependents_that_cannot_be_asked_about_are_cannot_tell(tmp_path: Path) -> None:
    """Same first-class "I cannot tell you" as the lane's own pull requests.

    A close that would break another pull request must not go ahead on the grounds
    that nobody could be reached to ask.
    """
    answer = GhClient("definitely-not-installed-gh").pull_requests_based_on(
        branch="feature/x", remote_url=GITHUB, cwd=tmp_path
    )

    assert isinstance(answer, CannotTell)
    assert answer.remedy == "brew install gh"


def test_a_detached_lane_has_no_branch_for_anything_to_be_based_on(tmp_path: Path) -> None:
    answer = GhClient("definitely-not-installed-gh").pull_requests_based_on(
        branch=None, remote_url=GITHUB, cwd=tmp_path
    )

    assert isinstance(answer, NotApplicable)
    assert answer.reason == "detached"


# -- G3, G4: cannot tell ---------------------------------------------------------


def test_gh_missing_says_how_to_install_it(tmp_path: Path) -> None:
    answer = GhClient("definitely-not-installed-gh").pull_request_for(
        branch="b", remote_url=GITHUB, cwd=tmp_path
    )

    assert isinstance(answer, CannotTell)
    assert answer.reason == "gh-missing"
    assert answer.remedy == "brew install gh"


def test_gh_logged_out_says_how_to_log_in(tmp_path: Path) -> None:
    gh = _fake_gh(
        tmp_path,
        stderr="error: not logged into any GitHub hosts. Run gh auth login to authenticate.",
        code=4,
    )

    answer = GhClient(gh).pull_request_for(branch="b", remote_url=GITHUB, cwd=tmp_path)

    assert isinstance(answer, CannotTell)
    assert answer.reason == "gh-logged-out"
    assert answer.remedy == "gh auth login"


def test_an_unreadable_answer_is_cannot_tell_never_a_silent_pass(tmp_path: Path) -> None:
    gh = _fake_gh(tmp_path, stdout="<html>not json</html>")

    answer = GhClient(gh).pull_request_for(branch="b", remote_url=GITHUB, cwd=tmp_path)

    assert isinstance(answer, CannotTell)


def test_an_unexplained_failure_is_cannot_tell(tmp_path: Path) -> None:
    gh = _fake_gh(tmp_path, stderr="could not resolve host github.com", code=1)

    answer = GhClient(gh).pull_request_for(branch="b", remote_url=GITHUB, cwd=tmp_path)

    assert isinstance(answer, CannotTell)
    assert answer.reason == "gh-failed"


# -- G5, G6: not applicable, without invoking gh ---------------------------------


def test_a_non_github_remote_is_not_applicable_and_gh_is_never_run(tmp_path: Path) -> None:
    """`gh` is deliberately a command that would fail if it were invoked."""
    client = GhClient("definitely-not-installed-gh")

    answer = client.pull_request_for(
        branch="feature/x",
        remote_url="https://contoso.visualstudio.com/X/_git/Y",
        cwd=tmp_path,
    )

    assert isinstance(answer, NotApplicable)
    assert answer.reason == "not-github"


def test_a_detached_lane_is_not_applicable_and_gh_is_never_run(tmp_path: Path) -> None:
    client = GhClient("definitely-not-installed-gh")

    answer = client.pull_request_for(branch=None, remote_url=GITHUB, cwd=tmp_path)

    assert isinstance(answer, NotApplicable)
    assert answer.reason == "detached"


def test_a_repository_with_no_remote_is_not_applicable(tmp_path: Path) -> None:
    client = GhClient("definitely-not-installed-gh")

    answer = client.pull_request_for(branch="b", remote_url=None, cwd=tmp_path)

    assert isinstance(answer, NotApplicable)


# -- the history, and which of it decides -----------------------------------------


def _history(*pairs: tuple[int, PrState]) -> Found:
    return found(*[PullRequest(number=n, state=s, url=f"u{n}") for n, s in pairs])


@pytest.mark.parametrize(
    ("history", "expected"),
    [
        # The obvious one: a follow-up opened after an earlier one merged.
        ((((42, "OPEN"), (41, "MERGED"))), 42),
        # Age does not decide it. An open pull request is work that has not landed,
        # so it is the decisive one even when a newer one has already merged.
        ((((42, "MERGED"), (41, "OPEN"))), 41),
        # Nothing open, so the merged one is what the lane's state turns on.
        ((((42, "CLOSED"), (41, "MERGED"))), 41),
        # Nothing open and nothing merged: the newest is all there is to report.
        ((((42, "CLOSED"), (41, "CLOSED"))), 42),
    ],
)
def test_the_decisive_pull_request_is_the_one_holding_the_lane_open(
    history: tuple[tuple[int, PrState], ...], expected: int
) -> None:
    assert _history(*history).decisive.number == expected


@pytest.mark.parametrize(
    ("history", "expected"),
    [
        ((((42, "MERGED"),)), True),
        # The case that misleads: an earlier one landed, but the follow-up has not, so
        # the lane's work is not all in the base and nothing may claim it is.
        ((((42, "OPEN"), (41, "MERGED"))), False),
        ((((42, "CLOSED"),)), False),
        # Closed without merging alongside one that merged is still landed work.
        ((((42, "MERGED"), (41, "CLOSED"))), True),
    ],
)
def test_the_work_landed_only_when_something_merged_and_nothing_is_open(
    history: tuple[tuple[int, PrState], ...], expected: bool
) -> None:
    assert _history(*history).landed is expected


# -- E7, E8: convenience state ---------------------------------------------------


def test_state_remembers_the_last_project(xdg: Path) -> None:
    store = StateStore()

    store.remember_project("Acme.Widgets")

    assert store.load().last_project == "Acme.Widgets"
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


def test_state_lives_under_xdg_state_home_not_with_the_config(xdg: Path) -> None:
    assert StateStore().path == xdg / "xdg-state" / "lane" / "state.toml"


def test_a_missing_state_file_is_simply_empty(xdg: Path) -> None:
    assert StateStore().load() == State()


def test_a_corrupt_state_file_is_simply_empty(xdg: Path) -> None:
    store = StateStore()
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{{{ not toml")

    assert store.load() == State()


def test_saving_state_never_raises_even_when_it_cannot(xdg: Path, tmp_path: Path) -> None:
    """Losing this file must never interrupt what the user was doing."""
    blocked = tmp_path / "blocked"
    blocked.write_text("I am a file, not a directory")
    store = StateStore(blocked / "lane")

    store.remember_project("anything")  # must not raise

    assert store.load() == State()

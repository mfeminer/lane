"""The version comes from the git tag, and nowhere else.

Releasing is `git tag vX.Y.Z && git push --tags`. Nothing in the tree carries the
number, so nothing in the tree can disagree with the tag.
"""

from __future__ import annotations

import pytest

import lane
from lane import buildinfo, config


def test_the_version_is_generated_by_the_build_not_written_in_the_tree() -> None:
    """hatch-vcs writes `src/lane/_version.py` from `git describe`.

    It is generated at install and at build time, so it exists in a synced
    checkout, in a wheel and inside the binary. If this import ever fails, the
    fallback below it takes over and every build reports the same placeholder —
    which is exactly the failure this test exists to catch, because a wrong
    version number is invisible until someone reports a bug against it.
    """
    from lane import _version

    assert _version.__version__ == lane.__version__
    assert lane.__version__[:1].isdigit(), lane.__version__


@pytest.mark.parametrize(
    ("built", "stamped"),
    [
        ("0.0.2", "0.0.2"),
        ("0.1.0", "0.1.0"),
        ("1.2.3", "1.2.3"),
        # Between tags. The whole suffix moves with every commit.
        ("0.0.2.post1.dev2+g15365c9", "0.0.2"),
        ("0.0.2.post1.dev3+g0d4f1ab.d20260806", "0.0.2"),
        # No .git to describe.
        ("0+unknown", "0"),
    ],
)
def test_the_config_stamp_is_the_release_a_build_came_from(built: str, stamped: str) -> None:
    """config.toml records a release, not a build.

    An untagged build's version moves with every commit (`.dev2` → `.dev3`, a
    fresh hash), and the stamp is compared on every load. Writing the full
    version would rewrite the file — leaving a .bak beside it — every single
    run of a development checkout, announcing an upgrade that never happened.
    """
    assert buildinfo.release_of(built) == stamped


def test_the_stamp_lane_actually_writes_is_a_release() -> None:
    assert buildinfo.release_of(lane.__version__) == config.CONFIG_VERSION
    assert "+" not in config.CONFIG_VERSION

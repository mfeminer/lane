"""Putting one JSON document on stdout, and keeping everything else off it.

The rule is short and the whole point: **with `--json`, stdout is one JSON document
and nothing else**, so `lane list --json | jq …` is always valid. Everything lane
would otherwise say — a spinner, a `✓`, a refusal — is not suppressed, it is moved
to stderr, because a script that cannot see why something was refused is worse off
than one that has to redirect.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def emit(document: Any) -> None:
    """The only thing in lane that writes to stdout in `--json` mode."""
    json.dump(document, sys.stdout, indent=None, default=str)
    sys.stdout.write("\n")

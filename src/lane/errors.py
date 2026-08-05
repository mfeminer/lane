"""Errors that reach the user as prose."""

from __future__ import annotations


class LaneError(Exception):
    """Something lane refuses to do, phrased for the person reading it."""


class PrerequisiteMissing(LaneError):
    """A tool lane cannot work without is absent."""

    def __init__(self, tool: str, remedy: str) -> None:
        super().__init__(f"{tool} is not installed")
        self.tool = tool
        self.remedy = remedy

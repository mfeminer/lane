"""Lanes on disk, and the metadata kept beside them.

A lane is a worktree at `<lanes_root>/<project>/<lane>`.

Its metadata — description, base branch, when it was created, which repository it
came from — is deliberately kept **outside** the worktree, at
`<lanes_root>/<project>/.lane/<lane>`. Inside, it would show up as an uncommitted
change in the very listing that reports uncommitted changes.

A lane whose metadata has gone missing must still list and still close: the
metadata is a convenience, and the worktree is the truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

METADATA_DIRNAME = ".lane"
_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"


@dataclass(frozen=True, slots=True)
class LaneMeta:
    description: str = ""
    base: str = ""
    created: str = ""
    repo: str = ""
    start: str = ""
    """The commit this lane was created at.

    Without it there is no way to tell "this lane has done no work" from "this
    lane's work has landed in the base branch": in both cases nothing is ahead of
    `origin/<base>`. Lanes created before this was recorded simply have it empty,
    and fall back to the weaker check.
    """

    @property
    def created_at(self) -> datetime | None:
        for pattern in (_TIMESTAMP_FORMAT, "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(self.created, pattern)
            except ValueError:
                continue
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        return None


@dataclass(frozen=True, slots=True)
class Lane:
    project: str
    name: str
    path: Path
    meta: LaneMeta

    @property
    def slug(self) -> str:
        return f"{self.project}/{self.name}"

    def repo_path(self, projects_root: Path | None) -> Path:
        """Where the lane came from: what the metadata says, else the obvious guess."""
        if self.meta.repo:
            return Path(self.meta.repo)
        if projects_root is not None:
            return projects_root / self.project
        return self.path

    def description(self) -> str:
        return self.meta.description or self.name

    def age_days(self, now: datetime | None = None) -> int | None:
        created = self.meta.created_at
        if created is None:
            return None
        moment = now or datetime.now(UTC)
        return max(0, (moment - created).days)


def age_phrase(days: int | None) -> str:
    """Human wording for a lane's age. Empty when it cannot be known."""
    if days is None:
        return ""
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 14:
        return "last week"
    if days < 60:
        return f"{days // 7} weeks ago"
    return f"{days // 30} months ago"


class LaneStore:
    """Finds lanes and looks after their metadata."""

    def __init__(self, lanes_root: Path) -> None:
        self._root = lanes_root

    @property
    def root(self) -> Path:
        return self._root

    def project_dir(self, project: str) -> Path:
        return self._root / project

    def lane_path(self, project: str, name: str) -> Path:
        return self._root / project / name

    def metadata_dir(self, project: str) -> Path:
        return self._root / project / METADATA_DIRNAME

    def metadata_file(self, project: str, name: str) -> Path:
        return self.metadata_dir(project) / name

    # -- discovery -----------------------------------------------------------
    def list_lanes(self) -> list[Lane]:
        """Every lane under the root, sorted by project then name."""
        if not self._root.is_dir():
            return []
        found: list[Lane] = []
        try:
            projects = sorted(self._root.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return []
        for project_dir in projects:
            if not project_dir.is_dir() or project_dir.name == METADATA_DIRNAME:
                continue
            try:
                candidates = sorted(project_dir.iterdir(), key=lambda p: p.name.lower())
            except OSError:
                continue
            for candidate in candidates:
                if not candidate.is_dir() or candidate.name == METADATA_DIRNAME:
                    continue
                # A worktree's `.git` is a file pointing back at the main repository.
                if not (candidate / ".git").exists():
                    continue
                found.append(
                    Lane(
                        project=project_dir.name,
                        name=candidate.name,
                        path=candidate,
                        meta=self.read_meta(project_dir.name, candidate.name),
                    )
                )
        return found

    def exists(self, project: str, name: str) -> bool:
        return self.lane_path(project, name).exists()

    # -- metadata ------------------------------------------------------------
    def read_meta(self, project: str, name: str) -> LaneMeta:
        """A missing or unreadable file yields empty metadata, never an error."""
        path = self.metadata_file(project, name)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            return LaneMeta()
        values: dict[str, str] = {}
        for line in text.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key.strip()] = value.strip()
        return LaneMeta(
            description=values.get("desc", ""),
            base=values.get("base", ""),
            created=values.get("created", ""),
            repo=values.get("repo", ""),
            start=values.get("start", ""),
        )

    def write_meta(self, project: str, name: str, meta: LaneMeta) -> None:
        directory = self.metadata_dir(project)
        directory.mkdir(parents=True, exist_ok=True)
        body = (
            f"desc={meta.description}\n"
            f"base={meta.base}\n"
            f"created={meta.created}\n"
            f"repo={meta.repo}\n"
            f"start={meta.start}\n"
        )
        self.metadata_file(project, name).write_text(body, encoding="utf-8")

    def forget(self, project: str, name: str) -> None:
        """Remove the metadata and any directories it leaves empty."""
        self.metadata_file(project, name).unlink(missing_ok=True)
        for directory in (self.metadata_dir(project), self.project_dir(project)):
            try:
                directory.rmdir()
            except OSError:
                # Not empty, or not there. Either way, nothing to do.
                break

    @staticmethod
    def timestamp(now: datetime | None = None) -> str:
        return (now or datetime.now(UTC).astimezone()).strftime(_TIMESTAMP_FORMAT)

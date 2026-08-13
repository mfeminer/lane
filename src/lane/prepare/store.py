"""The answers, in a file of lane's own beside the config.

`${XDG_CONFIG_HOME:-~/.config}/lane/prepare.toml`, mode 0600 in the same 0700
directory — it records which paths a project keeps outside git, which is a description
of where that project's secrets are.

## Why not `config.toml`

`ConfigStore.save()` rebuilds the file body from the three settings it knows about, so
**any key it does not know is dropped on write** — and the version stamp is compared on
every load, so a version bump rewrites the file. An unbounded structure in there would
be deleted by the first upgrade unless the migration code learned to round-trip unknown
data, and the migration code is the one part of the config that must never be wrong.

Beyond that: `Config` is three settings, each with a default, an environment override
and validation where it is asked for, and a per-project list of steps has none of those
properties. And a separate file can be deleted to reset every answer without touching
the three settings.

## Why a flat list of records

Nesting would put project names and paths in *key* position, where TOML wants them
quoted — and project names contain dots (`Acme.Widgets`) while paths contain slashes.
`tomli-w` would quote them correctly and the file would stop being something a person
can read. One growing list of records with a single shape says the same thing; grouping
by project is derived, which is all any screen needs.

## It never announces itself

No rewrite, no `.bak`, no upgrade notice. The config's machinery for that exists because
the three settings' *format* changed once, and the invariant that the upgrade notice
stays one short line is not served by a second file also having something to say. The
`version` key is written and read so a future format change has something to hang a
migration on, and is otherwise not acted upon.

An unreadable file means **nothing is remembered** — never an exception and never a
rewrite. The screen then asks again, which is itself the signal, and doctor names the
file.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import tomli_w

from lane.config import CONFIG_VERSION, config_home
from lane.prepare import Step, Verb

_DIR_MODE = 0o700
_FILE_MODE = 0o600


@dataclass(frozen=True, slots=True)
class Remembered:
    """Every answer on disk, and anything worth saying about how it was read."""

    steps: tuple[Step, ...] = ()
    problem: str | None = None

    def for_project(self, project: str) -> tuple[Step, ...]:
        """This project's answers, in the order they are applied.

        Looked up by **project name** — the identifier lane already uses for
        `Lane.project`, for `<lanes_root>/<project>` and for the listing's grouping. A
        recorded path would be a string comparison of paths, which is what `samefile`
        exists to avoid: on a case-insensitive filesystem two spellings of one
        directory are two keys. Keying by name also survives moving `projects_root`,
        which a path would not; a *renamed* project asks again, exactly as it already
        gets a fresh lanes directory and a fresh listing.
        """
        return tuple(step for step in self.steps if step.project == project)

    def projects(self) -> tuple[str, ...]:
        """Every project with at least one answer, in name order."""
        return tuple(sorted({step.project for step in self.steps}, key=str.lower))


class PrepareStore:
    """Reads and writes `prepare.toml`. Knows nothing about prompting."""

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = directory if directory is not None else config_home()

    @property
    def path(self) -> Path:
        return self._dir / "prepare.toml"

    # -- reading -------------------------------------------------------------
    def load(self) -> Remembered:
        if not self.path.exists():
            return Remembered()
        try:
            body = tomllib.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
            return Remembered(problem=f"Could not read {self.path}: {exc}")
        return Remembered(steps=tuple(_read_steps(body)))

    # -- writing -------------------------------------------------------------
    def save(self, steps: Sequence[Step]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._dir.chmod(_DIR_MODE)
        body: dict[str, object] = {"version": CONFIG_VERSION}
        recorded = [_write_step(step) for step in steps if step.usable]
        if recorded:
            body["step"] = recorded
        self.path.write_text(tomli_w.dumps(body), encoding="utf-8")
        self.path.chmod(_FILE_MODE)

    def remember(self, project: str, steps: Sequence[Step]) -> None:
        """Replace one project's answers, leaving every other project's alone."""
        kept = [step for step in self.load().steps if step.project != project]
        self.save([*kept, *steps])

    def add(self, step: Step) -> None:
        """Record one answer, replacing any earlier answer about the same subject."""
        kept = [existing for existing in self.load().steps if existing.key != step.key]
        self.save([*kept, step])

    def forget(self, step: Step) -> None:
        self.save([existing for existing in self.load().steps if existing.key != step.key])


def _read_steps(body: dict[str, object]) -> Iterable[Step]:
    """Everything the file says that this version understands, and nothing else.

    An unknown verb and an unknown key are both ignored rather than reported, so a file
    written by a later lane still loads in an earlier one.
    """
    raw = body.get("step")
    if not isinstance(raw, list):
        return
    for record in raw:
        if not isinstance(record, dict):
            continue
        step = _read_step(record)
        if step is not None and step.usable:
            yield step


def _read_step(record: dict[str, object]) -> Step | None:
    project = _text(record.get("project"))
    if not project:
        return None
    try:
        verb = Verb(_text(record.get("verb")))
    except ValueError:
        return None
    return Step(
        project=project,
        verb=verb,
        path=_text(record.get("path")),
        refresh=record.get("refresh") is True,
        command=_text(record.get("command")),
        directory=_text(record.get("directory")),
        unless=_text(record.get("unless")),
    )


def _write_step(step: Step) -> dict[str, object]:
    """Only the fields this verb uses, so the file reads as what it means."""
    record: dict[str, object] = {"project": step.project, "verb": str(step.verb)}
    if step.verb is Verb.RUN:
        record["command"] = step.command
        if step.directory:
            record["directory"] = step.directory
        if step.unless:
            record["unless"] = step.unless
        return record
    record["path"] = step.path
    if step.refresh:
        record["refresh"] = True
    return record


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""

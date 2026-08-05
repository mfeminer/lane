"""Shared prompts: choosing a project, and resolving a lane's base branch.

`choose_project` returns None when there is nothing to choose from, having
explained why — that is different from `Abandoned`, which means the user backed out.

There was a `choose_lane` here too. The listing does that job now, and does it
better: the same names, with the status that tells you which one you meant.
"""

from __future__ import annotations

from lane.context import Context
from lane.git.backend import GitError
from lane.lanes import Lane
from lane.projects import Project, diagnose, list_projects
from lane.ui.seam import Choice


def choose_project(context: Context, title: str = "Which project?") -> Project | None:
    """Pick a project, offering the last one used first."""
    projects = list_projects(context.projects_root, context.git)
    if not projects:
        explain_no_projects(context)
        return None

    # Remembering the last project saves a keystroke on the common case of opening
    # a second lane in the same repository.
    last = context.state_store.load().last_project
    ordered = sorted(projects, key=lambda p: (p.name != last, p.name.lower()))

    options = [
        Choice(
            label=project.name,
            value=project,
            hint="last used" if project.name == last else "",
        )
        for project in ordered
    ]
    return context.ui.choose(title, options)


def explain_no_projects(context: Context) -> None:
    """Say how many subfolders were looked at, and point at a nested layout."""
    ui = context.ui
    problem = diagnose(context.projects_root, context.git)

    if context.projects_root is None:
        ui.error("lane does not know where your projects are.")
        ui.detail("  Set a projects folder in settings.")
        return

    if not problem.root_exists:
        ui.error(f"Projects folder is missing: {problem.root}")
        ui.detail("  Fix the path in settings, or check it with doctor.")
        return

    ui.error(
        f"No projects in {problem.root} — none of its "
        f"{problem.subdirectory_count} subfolder(s) is a git repository."
    )
    ui.detail(f"  Expected {problem.root}/<project>/.git")

    suggested = problem.suggested_root
    if suggested is not None:
        ui.detail(f"  Your repositories look nested — found one at {problem.nested_example}")
        ui.detail(f"  Point the projects folder at {suggested} in settings.")
    else:
        ui.detail("  Fix the path in settings, or check it with doctor.")


def resolve_base(context: Context, lane: Lane) -> str | None:
    """A lane's base branch: what its metadata recorded, else ask git again."""
    if lane.meta.base:
        return lane.meta.base
    repo = lane.repo_path(context.projects_root)
    try:
        return context.git.default_branch(repo)
    except GitError:
        return None

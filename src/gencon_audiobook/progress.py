"""Shared Rich progress column customizations and progress bar factory."""

from __future__ import annotations

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    Task,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.text import Text

# Single shared console used by all progress bars AND the RichHandler in cli.py.
# When Progress and RichHandler share the same Console, Rich correctly interleaves
# log messages above the live progress bar instead of clobbering the same line.
shared_console = Console()


class TimeRemainingWithLabel(TimeRemainingColumn):
    """TimeRemainingColumn that appends ' remaining' to the rendered time."""

    def render(self, task: Task) -> Text:
        text = super().render(task)
        if text.plain.strip() and text.plain.strip() not in ("--:--", "-:--:--"):
            text.append(" remaining")
        return text


class ConditionalMofNColumn(MofNCompleteColumn):
    """MofNCompleteColumn that can be hidden per-task via a task field.

    If the task's ``show_count`` field is False, renders blank padding of the
    same width so columns remain aligned across tasks.
    """

    def render(self, task: Task) -> Text:
        if not task.fields.get("show_count", True):
            total = int(task.total) if task.total is not None else 1
            total_width = len(str(total))
            # Width matches f"{completed:{total_width}d}/{total}": 2*total_width + 1
            return Text(" " * (2 * total_width + 1))
        return super().render(task)


def standard_progress() -> Progress:
    """Return a Progress bar with the standard project column layout.

    All full-width progress bars (scrape, download, convert) use this factory
    so their columns are identical and visually aligned.

    Column order: spinner | N/M count | bar | percent | elapsed | remaining | description
    """
    return Progress(
        SpinnerColumn(),
        ConditionalMofNColumn(),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TimeRemainingWithLabel(compact=True),
        TextColumn("[progress.description]{task.description}"),
        console=shared_console,
    )

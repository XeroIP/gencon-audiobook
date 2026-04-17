"""Shared Rich progress column customizations."""

from __future__ import annotations

from rich.progress import MofNCompleteColumn, Task, TimeRemainingColumn
from rich.text import Text


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

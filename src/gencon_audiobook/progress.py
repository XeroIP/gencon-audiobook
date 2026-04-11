"""Shared Rich progress column customizations."""

from __future__ import annotations

from rich.progress import TimeRemainingColumn
from rich.text import Text


class TimeRemainingWithLabel(TimeRemainingColumn):
    """TimeRemainingColumn that appends ' remaining' to the rendered time."""

    def render(self, task: "Task") -> Text:  # type: ignore[override]
        text = super().render(task)
        if text.plain.strip() and text.plain.strip() not in ("--:--", "-:--:--"):
            text.append(" remaining")
        return text

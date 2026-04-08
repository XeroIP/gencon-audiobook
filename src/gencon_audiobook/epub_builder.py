"""Generate an EPUB 3 companion with transcripts and speaker photos."""

from __future__ import annotations

from pathlib import Path

from .models import Conference


def build_epub(
    conference: Conference,
    images_dir: Path,
    output_path: Path,
) -> None:
    """Build an EPUB 3 companion with full transcripts and speaker photos.

    Args:
        conference: Fully populated Conference with transcript_html on each Talk.
        images_dir: Directory containing cover.jpg and speakers/*.jpg.
        output_path: Path for the output .epub file.

    Raises:
        NotImplementedError: epub generation is implemented in Phase 2.
    """
    raise NotImplementedError("epub generation coming in Phase 2")

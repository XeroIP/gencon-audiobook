---
globs: src/**/*.py
---

# Code Style Rules

## Module structure
- `from __future__ import annotations` at the top of every module
- Module-level one-sentence docstring immediately after imports
- `logger = logging.getLogger(__name__)` in every module that logs

## Type hints
- Full type annotations on all function signatures and class attributes
- No `Any` unless genuinely unavoidable and documented with a comment explaining why
- Use `X | Y` union syntax (not `Optional[X]` or `Union[X, Y]`)

## Docstrings
- Google-style docstrings on all public functions and methods
- Include `Args:`, `Returns:`, and `Raises:` sections where applicable
- One-sentence summary on the first line, blank line before sections

## Comments
- Comments explain WHY, not WHAT
- No commented-out code — delete it, git has history
- TODO comments require a GitHub issue reference: `# TODO(#42): Add multi-language support`

## Imports
- Relative imports within the package (`from .models import Talk`)
- Standard library first, third-party second, local third — separated by blank lines

## Logging
- Use `logging.getLogger(__name__)` — never the root logger directly
- DEBUG: diagnostic details (URLs fetched, selectors matched, file paths, ffmpeg commands)
- INFO: key milestones the user should see (scraping started, download progress, output created)
- WARNING: non-fatal issues (speaker photo missing, falling back to secondary selector, retrying)
- ERROR: recoverable failures (single download failed after retries, single talk parse failed)
- CRITICAL: unrecoverable failures (no talks found, ffmpeg unavailable, output dir not writable)
- No emojis in any log message or string literal

## General
- No emojis anywhere in source code, output strings, or generated file content
- Prefer explicit over implicit
- Raise exceptions with actionable context: what failed, what input, what to try next

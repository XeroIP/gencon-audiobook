# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.2] - 2026-04-09

### Added
- Completion report printed after every successful run: total duration, chapter count,
  source and output audio quality (bitrate/sample rate), file sizes, per-phase timing,
  and a list of any talks that failed to download.
- `BuildStats` dataclass returned by `build_m4b()` for callers that need quality metadata.
- Per-phase timing (scrape, download, audiobook, epub) using `time.monotonic()`.
- `reset_robots_cache()` public function in `scraper.py` for test isolation.
- `py.typed` PEP 561 marker file so mypy users get type information from the package.
- `[project.urls]` in `pyproject.toml` (Homepage, Repository, Bug Tracker) for PyPI display.
- `keywords` in `pyproject.toml` for PyPI discoverability.
- ruff and mypy CI jobs on every push/PR.
- Coverage report CI job (`pytest --cov`) on every push/PR.
- Python 3.13 added to the CI test matrix.
- Explicit `permissions` blocks on all GitHub Actions workflows (least-privilege).
- All GitHub Actions pinned to commit SHAs for supply-chain security.
- Live test deduplication: consecutive failures add a comment to the existing issue
  instead of opening a duplicate.

### Fixed
- Ghost zero-length chapter in the m4b output when a talk's MP3 was missing. Previously,
  skipped talks contributed a dead chapter entry visible in audio players. Only successfully
  converted talks now appear as chapters.
- `ffprobe_path` was silently re-derived inside `convert_mp3_to_aac`, ignoring the path
  passed by `build_m4b`. This broke setups where ffprobe is installed separately from ffmpeg.
- HTTP 429 (Too Many Requests) was incorrectly treated as a fatal error. It is now retried
  with exponential backoff like other transient failures.
- Single quotes in the parent directory path caused a malformed ffmpeg concat file.
  Full resolved paths are now properly escaped (`'` → `'\''`).
- Subprocess `_run()` had no timeout, allowing a hung ffmpeg process to block indefinitely.
  A 600-second timeout now raises `AudioError` with an actionable message.
- ASCII transliteration in chapter titles now falls back to the original text when conversion
  yields an empty string (e.g. for non-Latin scripts), rather than producing a blank title.
- `\r` (carriage return) was not escaped in FFMETADATA1 chapter metadata, which could produce
  malformed metadata files on some inputs.
- `data:` URIs were not stripped during EPUB transcript sanitization, allowing potential
  embedding of active content. They are now removed alongside `javascript:` URIs.
- Dead `skipped` counter in `download_conference` was initialized but never incremented;
  the associated log block was unreachable code. Both have been removed.

### Security
- User-Agent is now derived at import time from the installed package version (`__version__`),
  eliminating the stale hardcoded `0.1.0` string present in both `scraper.py` and
  `downloader.py`. The string now correctly reflects the running version.
- EPUB sanitizer strips `data:` URI scheme in addition to `javascript:` and external URLs.
- PyPI publish workflow now requires tests to pass before uploading; the GitHub release job
  now requires the publish job to succeed before creating the release.
- All GitHub Actions use per-job permissions rather than broad workflow-level grants.

### Changed
- `User-Agent` string is now defined once in `utils.py` and imported by all HTTP clients.
- Shared test helpers (`make_silent_mp3`, `make_jpeg`, `requires_ffmpeg`) consolidated in
  `conftest.py`, eliminating duplication across `test_audio.py`, `test_epub.py`, and
  `test_integration.py`.
- Step comment numbering in `build_m4b` corrected (was off-by-one after Step 1).
- Various code-style compliance improvements: `from __future__ import annotations` added to
  all modules; named constants for magic numbers; PIL image operations wrapped in `with`
  statements; `Image.Resampling.LANCZOS` replaces deprecated `Image.LANCZOS`.

## [0.1.1] - 2025-12-01

Internal version bump. No functional changes; not published to PyPI.

## [0.1.0] - 2025-11-15

Initial release.

### Added
- `scraper.py`: scrapes all available General Conference sessions from
  `churchofjesuschrist.org`, including talk titles, speakers, MP3 URLs, transcripts,
  speaker photos, and cover images. Respects `robots.txt` and rate-limits requests.
- `downloader.py`: downloads MP3s, the conference cover image, and speaker photos with
  resume support (skips files already the correct size), atomic `.tmp` → rename writes,
  exponential retry backoff, and JPEG conversion for all images.
- `audio.py`: converts MP3s to AAC, builds FFMETADATA1 chapter files with millisecond
  offsets, concatenates and muxes into a chaptered `.m4b` audiobook with optional cover
  art, and verifies the output with ffprobe.
- `epub_builder.py`: builds an EPUB 3.0 companion with a cover page, copyright page,
  navigable TOC, and per-talk chapters containing speaker photos, bylines, and full
  sanitized transcripts. Output passes epubcheck with zero errors.
- `ffmpeg_manager.py`: locates ffmpeg/ffprobe on `PATH`; falls back to `static-ffmpeg`
  if not found; caches the result for the process lifetime.
- `cli.py`: Click-based CLI with `--output`, `--conference`, `--audiobook-only`,
  `--epub-only`, `--verbose`, `--overwrite`, `--bitrate`, and `--sample-rate` flags.
  Includes disk-space warning, robots.txt check, resume behavior, and a Rich progress
  display during downloads and conversion.
- URL allowlist restricting all HTTP requests to `churchofjesuschrist.org` and
  `*.ldscdn.org` domains.
- Filename sanitization preventing path traversal and special characters in output paths.
- Fixture-based unit tests for scraper, downloader, audio pipeline, EPUB builder, and
  utilities; weekly live smoke test workflow with automatic GitHub issue creation on failure.

[Unreleased]: https://github.com/XeroIP/gencon-audiobook/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/XeroIP/gencon-audiobook/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/XeroIP/gencon-audiobook/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/XeroIP/gencon-audiobook/releases/tag/v0.1.0

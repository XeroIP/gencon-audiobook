# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Progress indicators now show elapsed time on long-running progress bars and spinner phases.
- Download status messages now show audio/image count breakdowns.

### Fixed
- `--prefer-video-audio` extraction now writes `.m4a.tmp` files with an explicit ffmpeg muxer, fixing Windows extraction failures where ffmpeg could not infer the output format.
- `--prefer-video-audio` now falls back to the MP3 URL for an individual talk if video-audio extraction fails.
- Fully cached `--prefer-video-audio` reruns skip the heavy download confirmation and avoid misleading no-op timing output.
- `--audiobook-only` and `--epub-only` are now rejected as mutually exclusive flags before scraping or downloading.
- Missing `--output` values now produce a direct option-value error instead of an unrelated extra-argument error.
- Missing direct conference URLs now report the requested conference as unavailable instead of retrying and blaming internet connectivity.
- If every talk audio download fails, the CLI now stops before audiobook build with a clear error and log path.

### Changed
- Video-audio decision banners are styled so important warning/active states stand out without coloring the full prompt body.

## [0.2.0rc1] - 2026-04-29

### Added
- `--prefer-video-audio` flag: when a conference's 360p video audio is better than the MP3 source, the tool can extract the 96 kbps AAC track from video instead of downloading lower-quality MP3 audio. The default run warns before downloading, the opt-in path shows estimated download/audio-cache sizes, and newer conferences with better MP3 audio are protected from downgrade.
- EPUB table-of-contents entries now include speaker names.
- Completion reports now include session count and session names.

### Fixed
- Scraper fetches now enforce robots.txt through the shared `_fetch()` path, matching the documented behavior.

## [0.1.8] - 2026-04-28

### Fixed
- EPUB footnotes now render correctly end-to-end. The scraper was discarding the
  `<footer class="notes">` section (footnote bodies live outside `div.body-block`);
  it now appends footer content to `transcript_html`. The EPUB builder was only
  recognising bare `#noteN` fragment hrefs as note-refs, but the Church site
  generates full talk-page URLs (e.g. `/study/general-conference/2024/04/31bowen?lang=eng#note1`);
  these are now detected via `class="note-ref"` + `data-scroll-id` and normalised
  to bare fragments before being marked `epub:type="noteref"`. Footnote-body
  wrapping is tightened to `id` values matching `^note\d+$` only, preventing
  section-heading (`note_title1`) and child-paragraph (`note1_p1`) elements from
  being incorrectly wrapped as `<aside epub:type="footnote">`.

### Changed
- CI workflow now runs on both `main` and `dev` branches (push and pull_request).
- `pip-audit` job ignores `CVE-2026-3219` (affects `pip` itself with no fix
  version available at time of release).

### Added
- `build>=1.2` added to dev extras so `python -m build` works out of the box.
- 6 new unit tests covering the footnote pipeline, including a ZIP-level
  assertion that `epub:type="noteref"` and `epub:type="footnote"` appear in the
  final EPUB output.
- `tests/fixtures/talk_page_with_notes.html` — realistic Church HTML fixture
  with `div.body-block` + `footer.notes` for regression testing.

## [0.1.7] - 2026-04-16

### Added
- `--epub-paragraph-numbers` flag: adds left-margin paragraph numbers to every talk transcript in the EPUB. Numbers restart at 1 per talk and are styled with `float: left` in a 2em gutter (CSS class `.para-num`). Each numbered paragraph also receives an `id="pN"` attribute for potential deep-linking. Paragraphs inside footnote `<aside>` elements are excluded. Off by default; useful for study groups and citations (e.g. "Elder Holland, paragraph 7").

### Fixed
- Documentation drift: README, `docs/spec.md`, `docs/scraper-pipeline.md`, and `CLAUDE.md` updated to reflect features added through v0.1.6 (`cache.py`, `progress.py`, `InlineImage`, `inline/` directory, `--force-scrape`, parallel image downloads).
- Wiki Technical-Decisions §13 corrected: console log level is WARNING by default, not INFO.
- Wiki updated with 6 new Technical-Decisions sections: conference metadata caching, parallel image downloads, EPUB 3 popup footnotes, portrait cover image, ZIP_STORED for JPEG entries, IIIF URL resolution upgrade.

## [0.1.6] - 2026-04-15

### Added
- EPUB 3 popup footnotes: footnote superscript links (`href="#note*"`) are now preserved through sanitization with `epub:type="noteref"`, and footnote body elements are wrapped in `<aside epub:type="footnote">`. Modern e-readers (Apple Books, Kobo, Thorium) display footnotes as dismissible popovers; older readers fall back to an in-page jump.
- Conference metadata cache: scraped `Conference` data is written to `conference.json` after the first run. Subsequent runs load from cache, skipping ~38 HTTP requests per conference. Use `--force-scrape` to bypass.
- Parallel image downloads: cover image, speaker photos, and inline body images now download concurrently (up to 8 threads), each with its own `requests.Session`. Audio MP3s remain sequential.

### Fixed
- INFO-level log lines no longer appear on the console during normal runs. Console handler threshold raised from INFO to WARNING; DEBUG and INFO messages still appear in the log file and with `--verbose`.

## [0.1.5] - 2026-04-11

### Added
- Portrait cover image: landscape source image is centered on a 1200x1800 gray canvas, producing a proper 2:3 portrait cover for reader library grids.
- Session divider pages in the EPUB — each session gets a dedicated XHTML page so TOC session headers link to a unique destination rather than the first talk in the session.
- EPUB landmarks navigation (`<nav epub:type="landmarks">`) with cover, TOC, and bodymatter entries, improving compatibility with Kindle and accessibility tools.
- `epub:type` attributes on content documents: `"cover"` on cover.xhtml, `"chapter"` on all talk pages.
- Speaker photos now fetched at 800px resolution via IIIF URL upgrade (same technique already used for the conference cover), improving sharpness in the EPUB.
- Post-write ZIP integrity check: `testzip()` runs after the EPUB is written and raises `EpubError` if any entry is corrupt or the file is not a valid ZIP.
- `.transcript img` CSS rule added to constrain inline image sizing in reader apps.
- Release notes now include the CHANGELOG section for the tagged version, prepended above the auto-generated PR list in GitHub releases.

### Fixed
- JPEG images (cover, speaker photos, inline images) are now stored uncompressed (`ZIP_STORED`) in the EPUB ZIP, avoiding double-compression and compatibility issues on older e-ink readers.
- Footnote markers (`<sup data-value="1"></sup>`) now render visibly — the numeric value is materialized as text content before the `data-*` stripping pass removes the attribute.
- Web CSS class names stripped from EPUB transcript HTML — classes like `imageWrapper-wTPPD` and `body-block` reference React CSS with no EPUB rules.
- `dcterms:modified` in `content.opf` now reflects the actual build timestamp instead of a static conference date.

## [0.1.4] - 2026-04-11

### Added
- Inline talk body images are now downloaded and embedded in the EPUB. Images are extracted from talk pages (srcset parsed for largest resolution), stored in `output_dir/inline/`, resized to max 600px wide, and written into the EPUB ZIP with full OPF manifest entries.
- Per-talk ffmpeg progress bar with real-time encoding progress during AAC conversion; inner bar tracks each file, outer bar tracks total talks.

### Fixed
- EPUB filenames now use hyphens instead of spaces (e.g. `April-2024-General-Conference.xhtml`), resolving ~770 PKG-010/RSC-020 epubcheck errors caused by spaces in IRI path segments.
- All `<a>` link wrappers in EPUB transcripts are unwrapped (display text preserved), resolving ~900 RSC-033/RSC-026/RSC-007 epubcheck errors from unresolvable external links.
- `data-*` attributes and random web IDs stripped from EPUB transcript HTML, reducing XHTML file sizes by ~15-20% and removing React/JS rendering artifacts.
- Nav session headers changed from `<span>` to `<a>` linking to the first talk in the session, improving Kindle and reader app compatibility.
- Conference cover image resolution upgraded by rewriting IIIF URLs to request 800px wide images instead of the 250px thumbnail used on the website.

## [0.1.3] - 2026-04-11

### Added
- Rich progress bars and spinners across all pipeline phases: conference fetch, talk scraping (M/N bar with talk title), AAC conversion, download, m4b verification, and EPUB build.
- Countdown timer moved to immediately after the percentage on all progress bars, with "remaining" label (e.g. `02:15 remaining`).
- Conference name shown at the top of the completion report.

## [0.1.2] - 2026-04-09

### Added
- Completion report printed after every successful run: total duration, chapter count, source and output audio quality (bitrate/sample rate), file sizes, per-phase timing, and a list of any talks that failed to download.
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
- Live test deduplication: consecutive failures add a comment to the existing issue instead of opening a duplicate.

### Fixed
- Ghost zero-length chapter in the m4b output when a talk's MP3 was missing. Previously, skipped talks contributed a dead chapter entry visible in audio players. Only successfully converted talks now appear as chapters.
- `ffprobe_path` was silently re-derived inside `convert_mp3_to_aac`, ignoring the path passed by `build_m4b`. This broke setups where ffprobe is installed separately from ffmpeg.
- HTTP 429 (Too Many Requests) was incorrectly treated as a fatal error. It is now retried with exponential backoff like other transient failures.
- Single quotes in the parent directory path caused a malformed ffmpeg concat file. Full resolved paths are now properly escaped (`'` -> `'\''`).
- Subprocess `_run()` had no timeout, allowing a hung ffmpeg process to block indefinitely. A 600-second timeout now raises `AudioError` with an actionable message.
- ASCII transliteration in chapter titles now falls back to the original text when conversion yields an empty string (e.g. for non-Latin scripts), rather than producing a blank title.
- `\r` (carriage return) was not escaped in FFMETADATA1 chapter metadata, which could produce malformed metadata files on some inputs.
- `data:` URIs were not stripped during EPUB transcript sanitization, allowing potential embedding of active content. They are now removed alongside `javascript:` URIs.
- Dead `skipped` counter in `download_conference` was initialized but never incremented; the associated log block was unreachable code. Both have been removed.

### Security
- User-Agent is now derived at import time from the installed package version (`__version__`), eliminating the stale hardcoded `0.1.0` string present in both `scraper.py` and `downloader.py`. The string now correctly reflects the running version.
- EPUB sanitizer strips `data:` URI scheme in addition to `javascript:` and external URLs.
- PyPI publish workflow now requires tests to pass before uploading; the GitHub release job now requires the publish job to succeed before creating the release.
- All GitHub Actions use per-job permissions rather than broad workflow-level grants.

### Changed
- `User-Agent` string is now defined once in `utils.py` and imported by all HTTP clients.
- Shared test helpers (`make_silent_mp3`, `make_jpeg`, `requires_ffmpeg`) consolidated in `conftest.py`, eliminating duplication across `test_audio.py`, `test_epub.py`, and `test_integration.py`.
- Step comment numbering in `build_m4b` corrected (was off-by-one after Step 1).
- Various code-style compliance improvements: `from __future__ import annotations` added to all modules; named constants for magic numbers; PIL image operations wrapped in `with` statements; `Image.Resampling.LANCZOS` replaces deprecated `Image.LANCZOS`.

## [0.1.1] - 2025-12-01

Internal version bump. No functional changes; not published to PyPI.

## [0.1.0] - 2025-11-15

Initial release.

### Added
- `scraper.py`: scrapes all available General Conference sessions from `churchofjesuschrist.org`, including talk titles, speakers, MP3 URLs, transcripts, speaker photos, and cover images. Respects `robots.txt` and rate-limits requests.
- `downloader.py`: downloads MP3s, the conference cover image, and speaker photos with resume support (skips files already the correct size), atomic `.tmp` -> rename writes, exponential retry backoff, and JPEG conversion for all images.
- `audio.py`: converts MP3s to AAC, builds FFMETADATA1 chapter files with millisecond offsets, concatenates and muxes into a chaptered `.m4b` audiobook with optional cover art, and verifies the output with ffprobe.
- `epub_builder.py`: builds an EPUB 3.0 companion with a cover page, copyright page, navigable TOC, and per-talk chapters containing speaker photos, bylines, and full sanitized transcripts. Output passes epubcheck with zero errors.
- `ffmpeg_manager.py`: locates ffmpeg/ffprobe on `PATH`; falls back to `static-ffmpeg` if not found; caches the result for the process lifetime.
- `cli.py`: Click-based CLI with `--output`, `--conference`, `--audiobook-only`, `--epub-only`, `--verbose`, `--overwrite`, `--bitrate`, and `--sample-rate` flags. Includes disk-space warning, robots.txt check, resume behavior, and a Rich progress display during downloads and conversion.
- URL allowlist restricting all HTTP requests to `churchofjesuschrist.org` and `*.ldscdn.org` domains.
- Filename sanitization preventing path traversal and special characters in output paths.
- Fixture-based unit tests for scraper, downloader, audio pipeline, EPUB builder, and utilities; weekly live smoke test workflow with automatic GitHub issue creation on failure.

[Unreleased]: https://github.com/XeroIP/gencon-audiobook/compare/v0.2.0rc1...HEAD
[0.2.0rc1]: https://github.com/XeroIP/gencon-audiobook/compare/v0.1.8...v0.2.0rc1
[0.1.8]: https://github.com/XeroIP/gencon-audiobook/compare/v0.1.7...v0.1.8
[0.1.7]: https://github.com/XeroIP/gencon-audiobook/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/XeroIP/gencon-audiobook/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/XeroIP/gencon-audiobook/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/XeroIP/gencon-audiobook/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/XeroIP/gencon-audiobook/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/XeroIP/gencon-audiobook/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/XeroIP/gencon-audiobook/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/XeroIP/gencon-audiobook/releases/tag/v0.1.0

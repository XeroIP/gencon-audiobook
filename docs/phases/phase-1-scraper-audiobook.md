# Phase 1: Scaffolding + Scraper + Downloader + M4B Audiobook

## Objective

Produce a working CLI tool that scrapes all available General Conference recordings, lets the user
choose one, downloads audio and images, and assembles a chaptered m4b audiobook. When this phase
is complete, `gencon-audiobook --audiobook-only` must produce a valid m4b from a real conference.

Refer to `docs/spec.md` for all technical decisions, data models, dependency list, security
requirements, and website resilience strategy. Follow all rules in `.claude/rules/`.

---

## Prerequisites

- Empty repo with `CLAUDE.md`, `.claude/rules/`, `.claude/settings.json`, and `docs/spec.md`
  already in place (completed before this phase)
- No existing source code

---

## Step 1: Project Scaffold

Create the following files:

### `pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "gencon-audiobook"
version = "0.1.0"
description = "Download General Conference talks as a complete audiobook (m4b) and epub with full transcripts"
readme = "README.md"
requires-python = ">=3.10"
license = {text = "MIT"}
authors = [{name = "XeroIP"}]

dependencies = [
    "click>=8.0",
    "requests>=2.28",
    "beautifulsoup4>=4.11",
    "mutagen>=1.47",
    "Pillow>=9.0",
    "rich>=13.0",
    "static-ffmpeg>=2.7",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "responses>=0.23",
    "pip-audit>=2.0",
]

[project.scripts]
gencon-audiobook = "gencon_audiobook.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/gencon_audiobook"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "live: marks tests that hit the real website (deselect with -m 'not live')",
    "integration: marks end-to-end integration tests",
]
```

### `.gitignore`

Standard Python gitignore plus:
```
*.m4b
*.epub
*.mp3
*.aac
*.tmp
/output/
/test_output/
*.log
.claude/settings.local.json
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.venv/
venv/
.coverage
htmlcov/
```

### Directory structure

Create all directories and stub `__init__.py` files:
```
src/gencon_audiobook/
  __init__.py       # version string only
  __main__.py       # python -m support
  models.py
  utils.py
  scraper.py
  downloader.py
  ffmpeg_manager.py
  audio.py
  epub_builder.py   # stub only in Phase 1
  cli.py

tests/
  conftest.py
  fixtures/         # HTML snapshots go here
  test_scraper.py
  test_scraper_live.py
  test_downloader.py
  test_audio.py
  test_utils.py
  test_integration.py  # stub only in Phase 1

scripts/
  update_fixtures.py
```

---

## Step 2: `src/gencon_audiobook/__init__.py`

```python
"""gencon-audiobook: Download General Conference talks as m4b audiobook and epub."""
__version__ = "0.1.0"
```

## Step 3: `src/gencon_audiobook/__main__.py`

```python
"""Entry point for python -m gencon_audiobook."""
from gencon_audiobook.cli import main

main()
```

---

## Step 4: `models.py`

Implement exactly as specified in `docs/spec.md` — Conference, Session, Talk dataclasses with
full type annotations and Google-style docstrings.

Key requirements:
- `Conference.talks` property returns all talks across all sessions in order
- All fields that may be absent use `| None` with a `None` default
- `from __future__ import annotations` at top

---

## Step 5: `utils.py`

Implement two public functions:

### `sanitize_filename(name: str) -> str`
- Replace characters outside `[a-zA-Z0-9 ._-]` with underscores
- Collapse multiple consecutive underscores to one
- Strip leading/trailing underscores and spaces
- Truncate to 200 characters
- If result is empty, return "unnamed"
- Never return a string that would be a path traversal (`..`, starts with `/`, contains null bytes)

### `validate_url(url: str) -> bool`
- Return True only if the URL's hostname matches the allowlist:
  - `churchofjesuschrist.org`
  - `*.ldscdn.org`
  - `media*.churchofjesuschrist.org`
- Return False for anything else
- Never raise — invalid URLs return False

Write comprehensive tests in `test_utils.py`:
- Sanitization: unicode, path traversal attempts, empty string, very long names, already-clean names
- URL validation: each allowlisted domain, subdomains, non-allowlisted domains, malformed URLs

---

## Step 6: `scraper.py`

This is the most critical and most fragile module. Build it for resilience.

### Public API

```python
def fetch_available_conferences() -> list[ConferenceRef]:
    """Fetch the list of all available conferences from the archive page.

    Returns a list of ConferenceRef (title + URL), ordered most-recent first.
    Raises ScraperError with a user-facing message if the archive page cannot be parsed.
    """

def scrape_conference(conference_url: str) -> Conference:
    """Scrape a single conference: parse listing, then fetch each talk page.

    Args:
        conference_url: URL of the conference listing page.

    Returns:
        Fully populated Conference with Sessions and Talks.

    Raises:
        ScraperError: with a message suitable for display to the user.
    """
```

Define a `ConferenceRef` dataclass:
```python
@dataclass
class ConferenceRef:
    title: str   # e.g., "April 2024 General Conference"
    url: str
    year: int
    month: int   # 4 or 10
```

Define `ScraperError(Exception)` for user-facing scraper failures.

### Internal functions (also test these)

- `parse_conference_archive(html: str) -> list[ConferenceRef]`
- `parse_conference_listing(html: str) -> list[Session]` (Sessions with Talk stubs)
- `parse_talk_page(html: str, talk_url: str) -> dict` (mp3_url, transcript_html, speaker_image_url)

### CSS Selector Strategy

For every key element, implement **primary + fallback selectors**:

```python
SELECTORS = {
    "conference_list": [
        # primary
        "a.year-line__link",
        # fallback
        "a[href*='/study/general-conference/']",
    ],
    "talk_list": [
        "a.doc-item__content",
        "a[href*='/study/general-conference/'][class*='item']",
    ],
    "mp3_url": [
        "a[download][href$='.mp3']",
        "a[href$='.mp3']",
    ],
    "transcript": [
        "div.body-block",
        "div[class*='body']",
        "article",
    ],
    "speaker_image": [
        "img.speaker-image",
        "div.author-img img",
        "img[class*='speaker']",
        "img[class*='author']",
    ],
    "speaker_name": [
        "p.author-name",
        "div.author-name",
        "[class*='author-name']",
    ],
    "talk_title": [
        "h1",
        "title",
    ],
    "cover_image": [
        "img.hero-image",
        "div[class*='hero'] img",
        "meta[property='og:image']",
    ],
}
```

Selector strategy: try each selector in order, use the first that returns results, log which
selector succeeded at DEBUG level. Log a WARNING if falling back to a non-primary selector.

### HTTP behavior

- Use `requests.Session()` with the configured User-Agent and timeouts (see `docs/spec.md`)
- 0.5s delay between requests (configurable, default from a module constant)
- Retry with exponential backoff (1s, 2s, 4s, 8s) on connection errors, timeouts, 5xx responses
- Detect bot/Cloudflare protection:
  - HTTP 403 or 429 -> raise ScraperError: "Access was blocked (HTTP {status}). The website may
    be blocking automated access. Try again later or open a GitHub issue."
  - Response body contains "challenge" or "cloudflare" (case-insensitive) -> same error
  - Response body is shorter than 1000 characters for a page that should have content -> log WARNING
- Respect `robots.txt` — check on first run and cache result for the session
- Log every URL fetched at DEBUG level

### Validation

After parsing, validate every Talk:
- `title` must be non-empty
- `speaker` must be non-empty
- `mp3_url` must pass `validate_url()`
- If any required field is missing, log ERROR and skip that talk (do not raise)
- If zero talks pass validation, raise ScraperError: "No valid talks found. The website structure
  may have changed. Please open a GitHub issue at github.com/XeroIP/gencon-audiobook."

### HTML fixtures and tests

After implementing the scraper, run `scripts/update_fixtures.py` to save current HTML to
`tests/fixtures/`. Save:
- `tests/fixtures/conference_archive.html` — the archive/listing page
- `tests/fixtures/conference_listing.html` — a single conference's talk list page
- `tests/fixtures/talk_page.html` — a single talk page

`test_scraper.py` must test against these fixtures:
- `test_parse_conference_archive_returns_conferences` — returns a non-empty list with titles and URLs
- `test_parse_conference_listing_returns_sessions_with_talks` — sessions have names and talks have titles/speakers
- `test_parse_talk_page_extracts_mp3_url` — mp3_url is non-None and passes validate_url()
- `test_parse_talk_page_extracts_transcript` — transcript_html is non-empty
- `test_parse_talk_page_missing_speaker_photo_returns_none` — handles gracefully
- `test_scraper_validates_talks` — talks with missing required fields are skipped
- `test_scraper_raises_on_zero_valid_talks` — ScraperError raised with clear message
- `test_scraper_detects_cloudflare_block` — 403 raises ScraperError with appropriate message

`test_scraper_live.py` must test:
- `fetch_available_conferences()` returns 40+ conferences (General Conference has been running since 1971)
- `scrape_conference(url)` for the most recent conference returns 30+ talks
- Each talk has non-empty title, speaker, mp3_url, transcript_html
- All mp3_urls pass validate_url()

---

## Step 7: `downloader.py`

### Public API

```python
def download_conference(
    conference: Conference,
    output_dir: Path,
    delay: float = 0.5,
) -> None:
    """Download all MP3s, cover image, and speaker photos for a conference.

    Files are downloaded to .tmp first, renamed on success. Existing files of
    the correct size are skipped (resume behavior). Speaker photos are converted
    to JPEG. Progress is shown via rich progress bars.

    Args:
        conference: Fully populated Conference object with mp3_urls set.
        output_dir: Directory to download into. Created if it doesn't exist.
        delay: Seconds to wait between HTTP requests.
    """

def download_file(
    url: str,
    dest: Path,
    session: requests.Session,
    timeout: tuple[int, int] = (30, 120),
    retries: int = 3,
) -> None:
    """Download a single file to dest, using .tmp + rename for atomicity.

    Skips download if dest already exists with expected size (from Content-Length).
    Cleans up .tmp file on failure.

    Args:
        url: URL to download. Must pass validate_url().
        dest: Final destination path.
        session: requests.Session to use.
        timeout: (connect_timeout, read_timeout) in seconds.
        retries: Number of retry attempts with exponential backoff.

    Raises:
        DownloadError: if download fails after all retries.
        ValueError: if url fails validate_url().
    """
```

Define `DownloadError(Exception)`.

### Key behaviors

- Validate URL with `validate_url()` before every request — raise ValueError on failure
- Download to `dest.with_suffix(dest.suffix + '.tmp')`, rename to `dest` on success
- On crash/interruption: `.tmp` files are cleaned up on next run startup
- Resume: compare expected size (from `Content-Length` header) to existing file size; skip if match
- Convert all images to JPEG via Pillow before saving (handles WebP, PNG, GIF, etc.)
- Speaker photos saved to `output_dir/speakers/NN-speaker-name.jpg` (zero-padded talk number)
- `rich` progress: one overall progress bar for all files, one inner bar for current file (bytes)
- On download failure after retries: log ERROR, continue with remaining files

### Tests (`test_downloader.py`) — all using `responses` mock

- `test_download_file_success` — file saved correctly, .tmp cleaned up
- `test_download_file_skips_existing` — file with correct size is skipped (no HTTP request made)
- `test_download_file_retries_on_503` — retries 3 times, succeeds on last attempt
- `test_download_file_raises_after_max_retries` — DownloadError raised after all retries fail
- `test_download_file_rejects_non_allowlisted_url` — ValueError raised
- `test_download_file_cleans_up_tmp_on_failure` — .tmp file does not exist after failure
- `test_download_conference_converts_images_to_jpeg` — output files are JPEG regardless of input format

---

## Step 8: `ffmpeg_manager.py`

### Public API

```python
def ensure_ffmpeg() -> Path:
    """Locate ffmpeg, downloading via static-ffmpeg if not on system PATH.

    Search order:
    1. System PATH (shutil.which("ffmpeg"))
    2. static-ffmpeg auto-download

    Logs the ffmpeg path and version at INFO level on first call.
    Result is cached — subsequent calls return immediately.

    Returns:
        Path to the ffmpeg binary.

    Raises:
        FfmpegNotFoundError: with install instructions if ffmpeg cannot be located or downloaded.
    """
```

Define `FfmpegNotFoundError(Exception)`.

Key behaviors:
- Cache the result after first call (module-level variable)
- If system ffmpeg found: log "Using system ffmpeg at {path} (version {version})"
- If static-ffmpeg used: log "Downloaded ffmpeg to {path} (version {version})"
- If both fail: raise FfmpegNotFoundError with message:
  "ffmpeg could not be found or downloaded. To install manually:
   - Windows: winget install ffmpeg
   - macOS: brew install ffmpeg
   - Linux: sudo apt install ffmpeg (or equivalent)
  Then re-run gencon-audiobook."
- Run `ffmpeg -version` to get version string, parse first line

---

## Step 9: `audio.py`

### Public API

```python
def build_m4b(
    conference: Conference,
    audio_dir: Path,
    output_path: Path,
    cover_path: Path | None,
    ffmpeg_path: Path,
) -> None:
    """Build a chaptered m4b audiobook from downloaded MP3 files.

    Process:
    1. Convert each MP3 to AAC using ffmpeg
    2. Write an ffmpeg FFMETADATA1 chapter file
    3. Concatenate all AAC files
    4. Mux chapters, cover art, and metadata into final m4b

    Chapter titles use format: "Talk Title -- Speaker Name"
    Sessions are represented as chapter groupings (no separate session chapters).

    Args:
        conference: Conference object with talk metadata and durations.
        audio_dir: Directory containing downloaded MP3 files.
        output_path: Path for the output .m4b file.
        cover_path: Optional path to JPEG cover art.
        ffmpeg_path: Path to ffmpeg binary from ensure_ffmpeg().

    Raises:
        AudioError: if any ffmpeg step fails.
    """

def convert_mp3_to_aac(
    mp3_path: Path,
    aac_path: Path,
    ffmpeg_path: Path,
) -> float:
    """Convert an MP3 file to AAC.

    Args:
        mp3_path: Input MP3 file.
        aac_path: Output AAC file path.
        ffmpeg_path: Path to ffmpeg binary.

    Returns:
        Duration of the audio in seconds.

    Raises:
        AudioError: if ffmpeg returns a non-zero exit code.
    """
```

Define `AudioError(Exception)`.

### ffmpeg encoding settings (required, no deviations)

```
-c:a aac -b:a 64k -ar 44100 -ac 1
```
- `aac`: built-in AAC encoder (NOT `libfdk_aac` — requires custom build, breaks static-ffmpeg)
- `64k`: adequate for speech, reasonable file size
- `44100`: standard sample rate for maximum player compatibility
- `-ac 1`: mono — speech content, no stereo benefit

### FFMETADATA1 chapter format

Write a metadata file with this format before the mux step:

```
;FFMETADATA1
title=April 2024 General Conference
artist=General Conference
album=April 2024 General Conference
date=2024

[CHAPTER]
TIMEBASE=1/1000
START=0
END=842000
title=Opening Remarks -- President Henry B. Eyring

[CHAPTER]
TIMEBASE=1/1000
START=842000
END=1634000
title=The First Great Commandment -- Elder Jeffrey R. Holland
```

- TIMEBASE must be `1/1000` (milliseconds)
- START and END are cumulative millisecond offsets across the entire audiobook
- Chapter title format: `"Talk Title -- Speaker Name"` (double hyphen, space on both sides)
- Pass the metadata file to ffmpeg: `-i metadata.txt -map_metadata 1`
- Calculate durations by running `ffprobe` (included with ffmpeg) on each AAC file after conversion

### Post-creation verification

After building, use mutagen to verify:
- Chapter count matches number of talks
- First and last chapter titles match expected format
- Cover art is embedded
- Log INFO: "Verified m4b: {chapter_count} chapters, {duration:.0f}s total"

### Tests (`test_audio.py`)

Generate short silent MP3 test fixtures programmatically using ffmpeg (do not commit audio files):
```python
def make_silent_mp3(path: Path, duration_seconds: float = 2.0, ffmpeg_path: Path = ...) -> None:
    """Generate a short silent MP3 for testing."""
```

Tests:
- `test_convert_mp3_to_aac_produces_aac_file` — output file exists and is non-zero size
- `test_convert_mp3_to_aac_returns_duration` — returned duration is within 0.1s of expected
- `test_build_m4b_with_three_talks` — m4b produced, verified with mutagen
- `test_build_m4b_chapter_titles` — titles follow "Title -- Speaker" format
- `test_build_m4b_chapter_count` — chapter count matches talk count
- `test_build_m4b_with_cover_art` — cover art present in mutagen metadata
- `test_audio_error_on_invalid_input` — AudioError raised for non-existent input

---

## Step 10: `cli.py` (Minimal for Phase 1)

Implement a minimal but functional CLI. Full error handling and polish comes in Phase 3.

```python
@click.command()
@click.option("--output", default="~/gencon-audiobook", show_default=True,
              help="Directory to save output files.")
@click.option("--conference", default=None,
              help="Conference to download (e.g., 'April 2024'). Defaults to most recent.")
@click.option("--audiobook-only", is_flag=True, default=False,
              help="Produce only the m4b audiobook, skip epub.")
@click.option("--epub-only", is_flag=True, default=False,
              help="Produce only the epub, skip audiobook. (Phase 2)")
@click.option("--verbose", is_flag=True, default=False,
              help="Enable DEBUG-level console output.")
@click.version_option()
def main(...):
```

Phase 1 CLI behavior:
1. If `--conference` not given: fetch conference list, print numbered menu, default to #1 (most recent)
2. Print disk space warning: "Note: approximately 500 MB of disk space required."
3. Scrape the selected conference
4. Download audio and images
5. Build m4b (unless `--epub-only`)
6. Print completion summary (no emojis)
7. Basic error handling: catch ScraperError, DownloadError, AudioError and print clean messages
   (full polish in Phase 3)

---

## Step 11: `scripts/update_fixtures.py`

```python
"""Fetch current HTML from the live site and save to tests/fixtures/.

Usage: python scripts/update_fixtures.py
"""
```

Fetches:
- Archive/listing page -> `tests/fixtures/conference_archive.html`
- Most recent conference listing -> `tests/fixtures/conference_listing.html`
- First talk from that conference -> `tests/fixtures/talk_page.html`

Uses the same HTTP client settings as the scraper (User-Agent, timeouts, delay).

---

## Phase 1 Test Plan

Run after implementation is complete. All steps must pass before starting Phase 2.

```bash
# 1. Install
pip install -e ".[dev]"

# 2. Unit tests
pytest tests/test_utils.py -v
pytest tests/test_scraper.py -v
pytest tests/test_downloader.py -v
pytest tests/test_audio.py -v

# 3. Update fixtures from live site
python scripts/update_fixtures.py
# Verify: tests/fixtures/ contains 3 HTML files, all non-empty

# 4. Live scraper smoke test
pytest tests/test_scraper_live.py -v -m live
# Expected: passes, returns 40+ conferences and 30+ talks for most recent

# 5. End-to-end audiobook only
gencon-audiobook --audiobook-only --output ./test_output
# Expected:
#   - Lists available conferences, selects most recent
#   - Prints disk space warning
#   - Downloads audio and images with progress bars
#   - Builds m4b
#   - Prints completion summary

# 6. Verify m4b output
# - File exists: test_output/<conference name>/<conference name>.m4b
# - File size: 150-250 MB (full conference)
# - Open in VLC: audio plays
# - Open in Apple Books or Smart AudioBook Player: chapters display as "Title -- Speaker"
# - Chapter count matches number of talks (typically 30-35)

# 7. Resume behavior
# Delete one MP3 from test_output, re-run:
gencon-audiobook --audiobook-only --output ./test_output --conference "April 2024"
# Expected: only the deleted file re-downloads; all others skipped

# 8. ffmpeg fallback (on clean venv without system ffmpeg)
# Expected: static-ffmpeg downloads ffmpeg, tool runs successfully

# 9. Coverage check
pytest --cov=gencon_audiobook --cov-report=term-missing \
       --ignore=tests/test_scraper_live.py \
       --ignore=tests/test_integration.py
```

**Exit criteria**: All unit tests pass, end-to-end produces a valid m4b with correct chapters.

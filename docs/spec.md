# gencon-audiobook — Project Specification

## What It Does

`gencon-audiobook` is a Python CLI tool that scrapes all available General Conference recordings
from churchofjesuschrist.org, lets the user choose a conference, downloads all talk MP3s and
images, converts and combines audio into a single `.m4b` audiobook with chapter markers (each
chapter attributed to its speaker), and generates an `.epub` companion with full talk transcripts
and speaker photos.

## Usage

```bash
pip install gencon-audiobook

gencon-audiobook                          # List available conferences, default to most recent
gencon-audiobook --conference "April 2024"  # Select a specific conference
gencon-audiobook --audiobook-only         # Produce only the m4b
gencon-audiobook --epub-only              # Produce only the epub
gencon-audiobook --output ~/Books         # Custom output directory
gencon-audiobook --verbose                # Enable DEBUG-level console output
gencon-audiobook --overwrite              # Overwrite existing output files
```

## Output Structure

```
~/gencon-audiobook/April 2024 General Conference/
  April 2024 General Conference.m4b     # Complete audiobook with chapters
  April 2024 General Conference.epub    # Transcript companion
  cover.jpg                             # Conference cover image
  audio/                                # Downloaded and converted audio
    001-sanitized-title.mp3             # Zero-padded talk_index, sanitized title
    001-sanitized-title.m4a             # Intermediate AAC (deleted after m4b is built)
    ...
  speakers/                             # Speaker photos (for reference and epub)
    001-speaker-name.jpg                # Zero-padded talk_index, sanitized speaker name
    ...
  gencon-audiobook.log                  # Full DEBUG log for troubleshooting
```

File naming convention: all downloaded files use `{talk_index:03d}-{sanitized_name}.ext`
where `talk_index` is the talk's 1-based position across the whole conference.
`sanitize_filename()` is applied to the name component. This ensures stable, sortable filenames
that both `downloader.py` and `audio.py` can compute independently from the Talk object.

---

## Technical Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Language | Python 3.10+ | Best ecosystem for scraping, audio, epub. Largest contributor pool. |
| HTML parser | `html.parser` (stdlib) | Zero install, cross-platform. Resilience over speed for a single-site tool. |
| ffmpeg sourcing | System PATH first, then `static-ffmpeg` fallback | Users with ffmpeg already installed (most Linux/macOS users) get zero overhead. New users get automatic download. |
| m4b chapters | ffmpeg FFMETADATA1 format | Only reliable method for writing MP4 chapter atoms. Mutagen used for post-creation verification only — mutagen cannot write chapters. |
| m4b audio | AAC-LC, source-matched bitrate/sample-rate, mono | Maximum compatibility across iOS and Android. HE-AAC has spotty Android support. Mono is correct for speech. Source quality is preserved by default; `--bitrate` and `--sample-rate` flags override. |
| m4b cover | Book-level JPEG only | Per-chapter images not reliably rendered by any player. |
| m4b chapters | `"Talk Title -- Speaker Name"` | MP4 chapter spec has no author field; speaker name embedded in title with em-dash separator. |
| EPUB generation | Manual ZIP of XHTML | `ebooklib` is unmaintained (last release 2022), has 100+ open bugs, and produces non-compliant EPUB 3 output. Manual generation gives full control and reliable epubcheck compliance. |
| EPUB standard | EPUB 3, reflowable | Supported by Apple Books, Google Play Books, Kindle (auto-converts), Calibre, Moon+ Reader. Fixed layout renders as garbled text on Android. |
| EPUB CSS | Zero color/font/size declarations | Full reader theme support (dark mode, sepia, custom fonts, accessibility) requires zero hardcoded visual styling. See `.claude/rules/epub-style.md`. |
| EPUB images | JPEG only | No WebP (older readers), no PNG for photos (transparency issues on dark backgrounds). |
| EPUB TOC | Nested by session | Session headers group talks logically; matches the conference structure users expect. |
| Conference scope | All available conferences | Users should be able to produce audiobooks for any conference, not just the most recent. |
| Distribution | PyPI | Standard, updatable, cross-platform. `pip install gencon-audiobook`. |
| Content language | English only for v1 | Multi-language is a future community contribution. |
| License | MIT (tool code only) | Open source, community-friendly. Downloaded content is copyright Intellectual Reserve, Inc. |

---

## Data Flow

```
churchofjesuschrist.org
        |
        v
  scraper.py  -------------------------------->  models.py
  (html.parser, primary+fallback selectors)       Conference / Session / Talk
  (all conferences, user selects one)
        |
        v
  downloader.py  ----------------------------->  output_dir/
  (.tmp + rename, resume, retry/backoff)          |-- *.mp3
  (JPEG conversion via Pillow)                    |-- cover.jpg
                                                  +-- speakers/*.jpg
        |
        |---------------------------------------->  audio.py
        |                                           (ffmpeg: MP3->AAC-LC 64k/44.1kHz/mono,
        |                                            concat, FFMETADATA1 chapters, cover art)
        |                                           -> Conference.m4b
        |
        +---------------------------------------->  epub_builder.py
                                                    (manual EPUB 3 ZIP of XHTML,
                                                     theme-safe CSS, nested TOC by session)
                                                    -> Conference.epub
```

---

## Data Models

```python
@dataclass
class ConferenceRef:
    """Lightweight reference returned by fetch_available_conferences()."""
    title: str   # e.g., "April 2024 General Conference"
    url: str     # Full URL to the conference listing page
    year: int
    month: int   # 4 for April, 10 for October

@dataclass
class Talk:
    title: str
    speaker: str
    talk_url: str
    mp3_url: str | None = None
    transcript_html: str | None = None
    speaker_image_url: str | None = None
    session_name: str = ""
    session_number: int = 0   # 1-indexed
    talk_number: int = 0      # 1-indexed within the session
    talk_index: int = 0       # 1-indexed across the whole conference (used for filenames)
    duration_seconds: float = 0.0  # set by audio.py during MP3->AAC conversion

@dataclass
class Session:
    name: str          # e.g., "Saturday Morning Session"
    number: int        # 1-indexed
    talks: list[Talk]

@dataclass
class Conference:
    title: str         # e.g., "April 2024 General Conference"
    year: int
    month: int         # 4 for April, 10 for October
    cover_image_url: str | None
    sessions: list[Session]
    conference_url: str

    @property
    def talks(self) -> list[Talk]:
        """All talks across all sessions, in order."""
        return [talk for session in self.sessions for talk in session.talks]
```

---

## Dependencies

```toml
[project]
requires-python = ">=3.10"

dependencies = [
    "click>=8.0",              # CLI framework
    "requests>=2.28",          # HTTP client
    "beautifulsoup4>=4.11",    # HTML parsing (uses html.parser — NOT lxml)
    "mutagen>=1.47",           # Audio metadata verification only (NOT for chapter writing)
    "Pillow>=9.0",             # Image processing (resize/convert speaker photos to JPEG)
    "rich>=13.0",              # Progress bars and terminal output
    "static-ffmpeg>=2.7",      # Fallback ffmpeg download if not on system PATH
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "responses>=0.23",         # Mock HTTP requests in unit tests
    "pip-audit>=2.0",          # Dependency vulnerability scanning
]
```

Dependencies intentionally NOT used:
- `lxml` — replaced by stdlib `html.parser`
- `ebooklib` — replaced by manual EPUB generation

---

## Module Responsibilities

| Module | Responsibility |
|---|---|
| `models.py` | Dataclasses: Conference, Session, Talk |
| `utils.py` | `sanitize_filename()`, `validate_url()` (allowlist enforcement) |
| `scraper.py` | Fetch all conference URLs, parse conference listing, parse talk pages, return Conference objects |
| `downloader.py` | Download MP3s, cover, speaker photos with retry/backoff, .tmp+rename, resume |
| `ffmpeg_manager.py` | Locate ffmpeg and ffprobe (system PATH first, static-ffmpeg fallback) |
| `audio.py` | Convert MP3->AAC, assemble m4b with FFMETADATA1 chapters and cover art |
| `epub_builder.py` | Generate EPUB 3 manually as ZIP of XHTML with theme-safe CSS |
| `cli.py` | Click CLI entry point, conference selection, disk space warning, error handling |
| `__init__.py` | Package version string |
| `__main__.py` | `python -m gencon_audiobook` support |

---

## Security Requirements

1. **URL allowlist** — Only fetch from `churchofjesuschrist.org`, `*.churchofjesuschrist.org`
   (covers www, assets, media, etc.), and `*.ldscdn.org`. Reject and log any other domain.
   MP3s are served from `assets.churchofjesuschrist.org`.
2. **Filename sanitization** — Strip characters outside `[a-zA-Z0-9 ._-]`. Prevent path
   traversal (`..`, absolute paths, null bytes). Truncate at 200 characters.
3. **SSL verification** — Always on. Never `verify=False`.
4. **No code execution** — Never `eval()` or `exec()` scraped content. JSON-parse only.
5. **Rate limiting** — Default 0.5s delay between HTTP requests. Not configurable via CLI.
6. **User-Agent** — `gencon-audiobook/<version> (open source; github.com/XeroIP/gencon-audiobook)`
7. **Timeouts** — HTML: connect=15s, read=30s. MP3: connect=30s, read=120s.
8. **No credentials** — All content is publicly accessible. No tokens or API keys.
9. **Dependency auditing** — `pip-audit` in CI on every push.
10. **ffmpeg verification** — Log binary path and version on first use.

---

## Website Resilience Strategy

The Church website will change. This is the most critical ongoing maintenance concern.

### Scraper resilience
- Primary + fallback CSS selectors for every key element (talk list, MP3 URL, transcript, speaker photo)
- Validate parsed data: every Talk must have title, speaker, and mp3_url before accepting
- Descriptive error on parse failure: "Could not find talk listings. The website structure may have
  changed. Please open a GitHub issue at github.com/XeroIP/gencon-audiobook."
- Detect bot/Cloudflare protection: challenge pages, 403s, empty content
- Exponential backoff on failures (1s, 2s, 4s) before giving up
- Respect `robots.txt`

### Conference listing resilience
- `fetch_available_conferences()` must handle the archive page changing structure
- Fall back to known conference URL patterns if the listing page fails
- The list of known conference years/months can serve as a last-resort fallback

### Testing strategy
1. **Fixture-based unit tests** (`test_scraper.py`) — Parse saved HTML snapshots. Fast,
   deterministic. Update fixtures when site changes, then fix the scraper.
2. **Live smoke test** (`test_scraper_live.py`) — Hit real site, verify 30+ talks with MP3s
   and transcripts. Marked `@pytest.mark.live`, skipped in normal CI.
3. **Weekly CI cron** (`live-test.yml`) — Auto-run live smoke test. On failure, open a GitHub
   issue: "Website structure may have changed" with full error details.
4. **Fixture update script** (`scripts/update_fixtures.py`) — Fetch current HTML from live site
   and save to `tests/fixtures/`. Run when site changes to update test baselines.

---

## Error Recovery

- All downloads use `.tmp` extension during transfer, renamed to final name on completion
- On startup, clean up any `.tmp` files left by a previous crash
- Resume by default: skip files that exist with expected size (checked via HTTP Content-Length)
- Download phase is separate from build phase — downloaded files persist even if m4b/epub build fails
- Partial failures (single talk download fails): log WARNING, skip that talk, continue with rest
- Report skipped talks in final summary so user knows output is incomplete

---

## Platform Compatibility

### m4b Audiobook

A single m4b file works on both iOS and Android without modification.

| Platform | Support | Notes |
|---|---|---|
| iOS | Native | Apple Books, BookPlayer, Bound. Chapters, cover art, metadata all render. |
| Android | Requires audiobook app | Smart AudioBook Player, Sirin Audiobook Player. Default music app and Google Play Books do NOT support m4b. |
| macOS/Windows | Via iTunes/Apple Music | Shows chapters. VLC plays audio but ignores chapters. |

README must note that Android users need Smart AudioBook Player or similar.

### EPUB

| Platform | Support | Notes |
|---|---|---|
| iOS/macOS | Apple Books | Native support. |
| Android | Google Play Books, Moon+ Reader, ReadEra | Play Books is built in. |
| Kindle | Send to Kindle | Amazon auto-converts EPUB to AZW3. MOBI is dead (deprecated 2022). |
| Desktop | Calibre, any EPUB reader | Calibre is the reference tool for validation. |

---

## Legal and Copyright

- **MIT License** (`LICENSE`) — Covers the tool's source code only.
- **Content copyright** (`LICENSE-CONTENT.md`) — Downloaded audio, transcripts, and images are
  copyright Intellectual Reserve, Inc. Permitted for personal, noncommercial use per the
  Church's Terms of Use.
- **README disclaimer** — Prominent notice that this is an unofficial tool, not affiliated with
  The Church of Jesus Christ of Latter-day Saints.
- **m4b metadata** — `comment` field: "Copyright [Year] Intellectual Reserve, Inc. All rights
  reserved. For personal, noncommercial use only."
- **epub copyright page** — First page after cover: Intellectual Reserve, Inc. notice.
- **Rate limiting** — 0.5s delay; responsible scraping to minimize server impact.
- **User-Agent transparency** — Tool identifies itself; does not impersonate a browser.

---

## Disk Space Requirements

- Working space during download: approximately 200-300 MB of MP3 files
- Final m4b output: approximately 150-200 MB
- Final epub output: approximately 10-15 MB
- Total: approximately 400-500 MB

The CLI warns the user about disk space requirements before beginning download.

---

## End-to-End Verification

After all phases, the following must work on a clean machine with only Python 3.10+ installed:

```bash
pip install gencon-audiobook
gencon-audiobook

# Expected output (no emojis):
#   Fetching available conferences...
#   Found 50 conferences. Defaulting to most recent: April 2024 General Conference
#   Note: approximately 500 MB of disk space required.
#   Downloading audio (34 talks)... [progress bar]
#   Downloading images (35 files)... [progress bar]
#   Building audiobook... done
#   Building epub... done
#
#   Output saved to: ~/gencon-audiobook/April 2024 General Conference/
#     April 2024 General Conference.m4b (187 MB, 34 chapters)
#     April 2024 General Conference.epub (12 MB, 34 talks)
```

Full test suite:
```bash
pytest tests/ -v --ignore=tests/test_scraper_live.py --ignore=tests/test_integration.py
pytest tests/test_scraper_live.py -v -m live
pytest --cov=gencon_audiobook --cov-report=term-missing --ignore=tests/test_scraper_live.py --ignore=tests/test_integration.py
```

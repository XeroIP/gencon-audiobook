# Implementation Prompt: `gencon-audiobook` — New Project

> **How to use this file**: This is a self-contained implementation prompt for Claude Code.
>
> **Option A — Feed it as a prompt**: Open Claude Code in an empty directory and paste the contents of this file as your first message. Claude will execute the phases in order.
>
> **Option B — Use as CLAUDE.md**: Copy this file to an empty directory as `CLAUDE.md`, open Claude Code there, and say: "Execute the implementation plan in CLAUDE.md, starting with Step 0. Work through each phase sequentially. After completing each phase, stop and present the test plan for me to verify before continuing to the next phase."
>
> **Important**: Work through one phase at a time. After each phase, run the test plan yourself before telling Claude to proceed. This is how you catch issues early.

---

## Context

This is a **brand new GitHub repository** inspired by [ChurchofJesusChristDev/General-Conference-to-Audiobook](https://github.com/ChurchofJesusChristDev/General-Conference-to-Audiobook). That project is a collection of browser console scripts and shell scripts that require users to copy JavaScript into Chrome DevTools, manually run curl commands, and use third-party macOS software (AudioBookBinder) to assemble an audiobook. It has no tests, no error handling, and breaks silently when the Church website changes.

This new project replaces that workflow with a single `pip install` command and a one-line CLI that produces a finished m4b audiobook and an epub companion with full talk transcripts — on Windows, macOS, and Linux.

### Working Style

**Be brutally honest and direct throughout the entire project.** This is a community-facing open-source tool and it must be high quality. Specifically:
- If a design choice is bad, say so immediately and explain why
- If code quality is insufficient, flag it — don't let it slide
- If an approach won't work on all three platforms, call it out before writing code
- If a dependency is a poor choice, explain the alternatives
- If test coverage is inadequate, demand more tests
- If documentation is unclear or incomplete, rewrite it
- Do not sugarcoat feedback at any phase — problems caught early are cheap, problems caught late are expensive

This directive is also embedded in `CLAUDE.md` so it persists across future Claude Code sessions.

---

## Step 0: Create the GitHub Repository

**This is the very first action. Nothing else happens until this is done.**

1. Create a **new** public GitHub repo: `XeroIP/gencon-audiobook`
   - Description: "Download General Conference talks as a complete audiobook (m4b) and epub with full transcripts"
   - NOT a fork of the original project — brand new repo
   - Initialize with README (will be overwritten in Phase 1)
   - Default branch: `main`
   - MIT license (for the tool code only — see Legal section)
2. Clone locally
3. README will credit the [original project](https://github.com/ChurchofJesusChristDev/General-Conference-to-Audiobook) as inspiration

---

## Legal & Copyright

General Conference audio and transcripts are copyrighted by **Intellectual Reserve, Inc.** The Church's Terms of Use permit downloading for personal, noncommercial use. This tool automates that personal use.

**What the project must include:**

1. **`LICENSE`** (MIT) — Covers the tool's source code only.
2. **`LICENSE-CONTENT.md`** — Prominent notice that downloaded content (audio, transcripts, images) is copyrighted by Intellectual Reserve, Inc., subject to the Church's [Terms of Use](https://www.churchofjesuschrist.org/legal/terms-of-use), and permitted for personal, noncommercial use only. The MIT license does NOT apply to downloaded content.
3. **README disclaimer** — Near the top:
   > **Disclaimer**: This is an unofficial tool not affiliated with The Church of Jesus Christ of Latter-day Saints. General Conference content is © Intellectual Reserve, Inc. All rights reserved. This tool downloads content for personal, noncommercial use as permitted by the Church's Terms of Use. Please respect the Church's intellectual property.
4. **Copyright in output files**:
   - m4b metadata `comment` field: "© [Year] Intellectual Reserve, Inc. All rights reserved. For personal, noncommercial use."
   - epub: copyright page as the first page after the cover
5. **Rate limiting** — Respectful scraping (0.5s delay) to avoid server impact
6. **User-Agent transparency** — Identify as `gencon-audiobook/<version>` (not impersonating a browser)

---

## Project Specification

### What it does

`gencon-audiobook` is a Python CLI tool that:
1. Scrapes the most recent General Conference from churchofjesuschrist.org
2. Downloads all talk MP3s and images (cover art, speaker photos)
3. Converts and combines audio into a single `.m4b` audiobook with chapter markers (each chapter attributed to its speaker)
4. Generates an `.epub` companion containing full talk transcripts with speaker photos
5. Automatically downloads ffmpeg on first run (no user prerequisites beyond Python)

### Usage

```bash
pip install gencon-audiobook
gencon-audiobook                    # Downloads most recent conference
gencon-audiobook --output ~/Books   # Custom output directory
```

### Output

```
~/gencon-audiobook/October 2024 General Conference/
├── October 2024 General Conference.m4b    # Complete audiobook with chapters
├── October 2024 General Conference.epub   # Transcript companion
├── cover.jpg                              # Conference cover image
└── speakers/                              # Speaker photos (for reference)
    ├── 01-speaker-name.jpg
    └── ...
```

---

## Technical Decisions (Locked In)

| Decision | Choice | Rationale |
|---|---|---|
| Language | Python 3.10+ | Best ecosystem for scraping, audio, epub. Largest contributor pool. |
| ffmpeg | Auto-download via `static-ffmpeg` | Zero user setup. Verified binaries per platform. |
| Distribution | PyPI (`pip install gencon-audiobook`) | Standard, updatable, cross-platform. |
| m4b audio | AAC-LC, 64 kbps, 44.1 kHz, mono | Maximum compatibility across iOS and Android players. HE-AAC has spotty Android support. |
| m4b images | Book-level cover only (JPEG) | Per-chapter images not reliably rendered by any player. |
| m4b chapters | Standard iTunes-compatible MP4 chapter atoms | Supported by Apple Books, Smart AudioBook Player, Sirin, BookPlayer, Bound. |
| epub | EPUB 3, reflowable, JPEG/PNG images only, simple CSS | Works on Apple Books, Google Play Books, Kindle (auto-converts), Calibre, Moon+ Reader. |
| Content language | English only for v1 | Multi-language is a future community contribution. |
| Conference scope | Most recent conference for v1 | Arbitrary conference selection added later. |
| License | MIT | Open source, community-friendly, no commercial plans. |
| Repo | Brand new GitHub repo | Clean start. Reference original project in README as inspiration. |

---

## Platform Compatibility Notes

### m4b Audiobook — Single File, All Platforms

A single m4b file works on both iOS and Android without modification.

**iOS**: Native support in Apple Books, BookPlayer, Bound. Chapters, cover art, and metadata all render correctly.

**Android**: Requires a dedicated audiobook player — the default music app and Google Play Books do **not** support m4b. Recommended players:
- **Smart AudioBook Player** (most popular, full chapter support)
- **Sirin Audiobook Player** (good metadata handling)

**Desktop**: VLC plays audio but ignores chapters. iTunes/Apple Music shows chapters on macOS/Windows.

**README must include**: a note that Android users need Smart AudioBook Player or similar, since Google Play Books does not support m4b.

**ffmpeg settings for maximum compatibility:**
```
-c:a aac -b:a 64k -ar 44100 -ac 1
```
Use the built-in `aac` encoder (not `libfdk_aac`, which requires a custom ffmpeg build and would break `static-ffmpeg`).

### epub — Single File, All Platforms

A single EPUB 3 file works on iOS, Android, Kindle, and desktop without conversion.

**Key compatibility rules:**
- Images: JPEG and PNG only (no WebP — older readers don't support it)
- CSS: Simple styling only — no `position: fixed`, no forced widths, no exotic properties. Use em/percentage units.
- Layout: Reflowable only (no fixed layout — Android renders fixed-layout epub as garbled text)
- Validation: Must pass `epubcheck` with zero errors (critical for Kindle conversion quality)
- **Theme compatibility**: The epub MUST fully support reader/device theme settings. This means:
  - **No hardcoded colors** — never set `color`, `background-color`, or `border-color` in CSS. Use `currentColor` where a color reference is needed. Let the reader app control all colors.
  - **No hardcoded fonts** — never set `font-family`. Let the reader's chosen font apply.
  - **No hardcoded font sizes** — use only relative units (`em`, `%`). Never `px` or `pt` for text.
  - **No hardcoded margins/padding in absolute units** — use `em` or `%` only.
  - **Dark mode**: With no hardcoded colors, the reader's dark mode/sepia/custom themes will work automatically. Images with transparency (PNG) should be avoided for decorative elements since they may look wrong on dark backgrounds — use JPEG for photos.
  - **High contrast / accessibility**: By deferring all styling to the reader, accessibility modes (large text, high contrast, dyslexia fonts) will work out of the box.
  - **Test**: Verify the epub looks correct in at least: default theme, dark mode, sepia mode, and with a custom font selected by the user.

**Kindle**: Now accepts EPUB natively via "Send to Kindle." Amazon auto-converts to AZW3 internally. MOBI format is dead (Amazon stopped accepting it in 2022). A valid, error-free EPUB produces clean Kindle output.

---

## Architecture

```
gencon-audiobook/                   # NEW REPO
├── pyproject.toml                  # Build config, dependencies, entry point
├── README.md                       # References original project as inspiration
├── LICENSE                         # MIT (tool code only)
├── LICENSE-CONTENT.md              # Copyright notice for downloaded Church content
├── CONTRIBUTING.md
├── .gitignore
├── .github/
│   └── workflows/
│       ├── test.yml                # Run tests on PR/push
│       ├── publish.yml             # Publish to PyPI on release tag
│       └── live-test.yml           # Weekly cron: detect website changes
│
├── CLAUDE.md                       # Claude Code project instructions
├── .claude/
│   ├── settings.json               # Claude Code permissions and hooks
│   └── rules/
│       ├── code-style.md           # Python coding standards for Claude
│       ├── testing.md              # Testing conventions for Claude
│       └── security.md             # Security rules for Claude
│
├── docs/
│   ├── user-guide.md              # ELI5-level user documentation (for the person running the tool)
│   ├── listening-guide.md         # Personal device guide for using the downloaded files
│   ├── technical-decisions.md     # Technical docs: every decision with rationale
│   └── architecture.md            # System architecture and data flow
│
├── src/
│   └── gencon_audiobook/
│       ├── __init__.py             # Package version
│       ├── __main__.py             # python -m gencon_audiobook support
│       ├── cli.py                  # Click CLI entry point
│       ├── models.py               # Dataclasses: Conference, Session, Talk
│       ├── scraper.py              # Fetch + parse conference pages
│       ├── downloader.py           # Download MP3s, images with retry/progress
│       ├── audio.py                # ffmpeg conversion, m4b assembly, chapters
│       ├── epub_builder.py         # Epub generation with transcripts
│       ├── ffmpeg_manager.py       # Auto-download and verify ffmpeg binary
│       └── utils.py                # Filename sanitization, path helpers
│
├── tests/
│   ├── conftest.py                 # Shared fixtures, HTML snapshot loader
│   ├── fixtures/
│   │   ├── conference_listing.html # Saved conference listing page
│   │   ├── talk_page.html          # Saved individual talk page
│   │   └── talk_page_changed.html  # Modified HTML for resilience testing
│   ├── test_scraper.py             # Scraper unit tests against fixtures
│   ├── test_scraper_live.py        # Live site smoke test (marked slow)
│   ├── test_downloader.py          # Download tests with mocked HTTP
│   ├── test_audio.py               # Audio pipeline tests
│   ├── test_epub.py                # Epub structure validation
│   ├── test_utils.py               # Filename sanitization edge cases
│   └── test_integration.py         # End-to-end: scrape → download → m4b + epub
│
└── scripts/
    └── update_fixtures.py          # Dev utility: refresh HTML snapshots from live site
```

### Key Dependencies

```toml
dependencies = [
    "click>=8.0",              # CLI framework
    "requests>=2.28",          # HTTP client
    "beautifulsoup4>=4.11",    # HTML parsing
    "lxml>=4.9",               # Fast HTML parser backend
    "mutagen>=1.47",           # Audio metadata + m4b chapters
    "ebooklib>=0.18",          # Epub generation
    "Pillow>=9.0",             # Image processing (resize/convert speaker photos to JPEG)
    "rich>=13.0",              # Progress bars and terminal output
    "static-ffmpeg>=2.7",      # Auto-download platform-specific ffmpeg binary
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "responses>=0.23",         # Mock HTTP requests in tests
]
```

### Data Models (`models.py`)

```python
@dataclass
class Talk:
    title: str
    speaker: str
    description: str
    talk_url: str
    mp3_url: str | None = None
    transcript_html: str | None = None
    speaker_image_url: str | None = None
    session_name: str = ""
    session_number: int = 0
    talk_number: int = 0
    duration_seconds: float = 0.0

@dataclass
class Session:
    name: str                  # e.g., "Saturday Morning Session"
    number: int
    talks: list[Talk]

@dataclass
class Conference:
    title: str                 # e.g., "October 2024 General Conference"
    year: int
    month: int
    cover_image_url: str | None
    sessions: list[Session]

    @property
    def talks(self) -> list[Talk]:
        """All talks across all sessions, in order."""
        return [talk for session in self.sessions for talk in session.talks]
```

---

## Claude Code Configuration

### `CLAUDE.md` (project root)

Project-level instructions that Claude reads at the start of every session. Must include:

```markdown
# gencon-audiobook

## Project Overview
Python CLI tool that downloads General Conference talks from churchofjesuschrist.org
and produces an m4b audiobook with chapters and an epub with full transcripts.

## Tone
Be brutally honest and direct. If a design choice is bad, say so and explain why.
If code quality is lacking, flag it immediately. Do not sugarcoat feedback.
This project serves a community and must be high quality.

## Build & Test Commands
- Install dev dependencies: `pip install -e ".[dev]"`
- Run all unit tests: `pytest tests/ -v --ignore=tests/test_scraper_live.py --ignore=tests/test_integration.py`
- Run live scraper test: `pytest tests/test_scraper_live.py -v -m live`
- Run integration tests: `pytest tests/test_integration.py -v`
- Run full suite with coverage: `pytest --cov=gencon_audiobook --cov-report=term-missing`
- Build package: `python -m build`

## Code Standards
- Python 3.10+, full type annotations on all function signatures
- Google-style docstrings with Args, Returns, Raises
- Logging: use `logging.getLogger(__name__)` in every module. DEBUG for diagnostics, INFO for user milestones, WARNING for non-fatal issues, ERROR for recoverable failures.
- Comments explain WHY, not WHAT. No commented-out code.
- No hardcoded colors, fonts, or absolute sizes in epub CSS

## Security Rules
- NEVER add `verify=False` to any HTTP request
- NEVER use `eval()` or `exec()` on scraped content
- ALL URLs must be validated against allowlist (churchofjesuschrist.org, *.ldscdn.org) before fetching
- ALL filenames must be sanitized before writing to disk
- NEVER disable SSL verification

## Copyright
Downloaded content is © Intellectual Reserve, Inc. Tool code is MIT.
Always embed copyright notices in output files (m4b metadata, epub copyright page).
```

### `.claude/settings.json`

```json
{
  "permissions": {
    "allow": [
      "Bash(pip install *)",
      "Bash(pytest *)",
      "Bash(python -m build)",
      "Bash(python -m gencon_audiobook *)",
      "Bash(git *)"
    ]
  }
}
```

### `.claude/rules/code-style.md`

Path-scoped to `src/**/*.py`:
- Type hints required on all function signatures
- Google-style docstrings on all public functions
- `from __future__ import annotations` at top of every module
- Module-level docstring (one sentence) at top of every file
- No `Any` type unless genuinely unavoidable
- Relative imports within the package

### `.claude/rules/testing.md`

Path-scoped to `tests/**/*.py`:
- Test functions named `test_<function>_<scenario>`
- Use fixtures in `conftest.py` for shared setup
- Mock external HTTP with `responses` library
- Mark live tests with `@pytest.mark.live`
- Assert with descriptive messages
- Never make real HTTP requests in unit tests

### `.claude/rules/security.md`

Path-scoped to `src/**/*.py`:
- Validate all URLs against domain allowlist before fetching
- Sanitize all filenames derived from external data
- Never disable SSL verification
- Never eval/exec scraped content
- Always set timeouts on HTTP requests
- Log all external URLs fetched at DEBUG level

---

## Documentation

### User Documentation (`docs/user-guide.md`)

ELI5-level instructions. Assume the reader has never used a terminal, pip, or Python before. Must include:

1. **What is this tool?** — Plain-English explanation: "This tool downloads General Conference talks and turns them into an audiobook you can listen to on your phone, and an ebook you can read."
2. **What you need first** — Python installation instructions with screenshots/links for each platform:
   - Windows: "Go to python.org, download the installer, check 'Add to PATH', click Install"
   - macOS: "Open Terminal, type `brew install python` or download from python.org"
   - Linux: "Python is probably already installed. Open a terminal and type `python3 --version`"
3. **Installing the tool** — `pip install gencon-audiobook` with copy-paste instructions
4. **Running the tool** — `gencon-audiobook` with expected output shown step by step
5. **Finding your files** — Where the audiobook and epub are saved, with file explorer navigation
6. **Listening to your audiobook**:
   - iPhone/iPad: "Open the Files app, find the .m4b file, tap it. It opens in Apple Books."
   - Android: "Install Smart AudioBook Player from the Play Store. Open it and navigate to the .m4b file." Explain that the default music app and Google Play Books do NOT work with .m4b files.
   - Computer: "Double-click the .m4b file. On Mac it opens in Apple Books. On Windows it opens in iTunes."
7. **Reading the epub**:
   - iPhone/iPad: "Tap the .epub file. It opens in Apple Books."
   - Android: "Open with Google Play Books, Moon+ Reader, or ReadEra."
   - Kindle: "Use Amazon's Send to Kindle to transfer the epub."
   - Computer: "Open with Calibre (free) or double-click to open in your default reader."
8. **Troubleshooting** — Common problems in Q&A format:
   - "It says 'command not found'" → PATH issue, with fix
   - "It says 'connection error'" → Check internet
   - "The audiobook has no chapters" → Which player are you using? Use a real audiobook player
   - "It stopped working after a website update" → Open a GitHub issue (link provided)
9. **Updating** — `pip install --upgrade gencon-audiobook`

### Device Guide (`docs/listening-guide.md`)

**Purpose**: A guide for users who have downloaded the files and want to know how to use them on their various devices. Focused on personal device setup.

Must be:
- **Friendly tone** — written for someone less comfortable with technology
- **Practical** — focuses on "here's how to open these files on your device"
- **Printable** — clean formatting, no complex layout

Contents:

1. **Your files** — "You've downloaded General Conference as an audiobook and an ebook. Here's how to use them on your devices."
2. **The audiobook file (.m4b)**:
   - **What it is**: "This is the complete General Conference as a single audiobook file with chapters for each talk."
   - **iPhone/iPad**: "Tap the file. It opens in Apple Books. You'll see chapters listed — tap any chapter to jump to that talk."
   - **Android**: "You'll need an audiobook app. We recommend Smart AudioBook Player (free on the Play Store). Open it, find the file, and play. Important: the regular music app and Google Play Books will NOT work with this file."
   - **Computer**: "On Mac, double-click to open in Apple Books. On Windows, open in iTunes. On any computer, VLC plays it but won't show chapters."
   - **How chapters work**: "Each talk is a separate chapter. You can skip between talks using the chapter controls in your player."
3. **The ebook file (.epub)**:
   - **What it is**: "This is the complete text of every talk, with speaker photos, organized by session."
   - **iPhone/iPad**: "Tap the file. It opens in Apple Books."
   - **Android**: "Open with Google Play Books (built in), or install Moon+ Reader for a better reading experience."
   - **Kindle**: "Email the .epub file to your Send-to-Kindle email address. It will appear in your Kindle library."
   - **Computer**: "Open with Calibre (free at calibre-ebook.com) or any ebook reader."
4. **Tips**:
   - "Listen to the audiobook during your commute and follow along in the epub at home"
   - "The epub works great for searching for a specific quote or scripture reference"

### Technical Documentation (`docs/technical-decisions.md`)

Every significant decision documented with: what was chosen, what alternatives were considered, and why. Includes:

1. **Language: Python** — Why not Node.js, Go, Rust. Ecosystem analysis for scraping + audio + epub.
2. **ffmpeg: auto-download via static-ffmpeg** — Why not require user install, why not bundle in release, licensing considerations (LGPL).
3. **Distribution: PyPI** — Why not standalone binaries, why not Docker, why not Homebrew.
4. **Audio format: m4b with AAC-LC 64kbps/44.1kHz/mono** — Why not HE-AAC (Android compatibility), why not higher bitrate (diminishing returns for speech), why mono (speech is mono content). Platform compatibility matrix.
5. **Epub: EPUB 3 with reflowable layout** — Why not EPUB 2, why not fixed layout, Kindle compatibility story. Why JPEG/PNG only (no WebP).
6. **Scraping: requests + BeautifulSoup** — Why not Selenium/Playwright (headless browser overkill for static content), why not scrapy (too heavy for single-site tool).
7. **Chapter metadata: "Title — Speaker" format** — Why speaker in chapter title (m4b chapter spec has no author field), why em-dash separator.
8. **Testing strategy** — Why fixture-based + live smoke + weekly cron. How to maintain when site changes.
9. **Copyright metadata in output files** — What copyright notices are embedded in the m4b (comment metadata field) and epub (copyright page), why they're included (Intellectual Reserve, Inc. owns the content), reference to Church Terms of Use, and how the copyright year is determined dynamically.
10. **Rate limiting: 0.5s delay** — Why 0.5s (respectful without being unnecessarily slow), ethical scraping principles, impact on Church servers, how this compares to browser-based browsing, and the risk of IP bans if removed.
11. **User-Agent transparency** — Why the tool identifies itself as `gencon-audiobook/<version>` instead of impersonating a browser. Ethical obligation to be identifiable. Allows the Church's infrastructure team to identify and contact the project if needed. Includes the GitHub repo URL in the User-Agent string for easy contact.
12. **Security decisions** — URL allowlisting rationale, filename sanitization approach, why no eval/exec.

The technical documentation must also include a **Logging & Troubleshooting** section:

13. **Logging & Troubleshooting** — How to view and use logs:
    - **Default output**: What the user sees during a normal run (INFO-level via `rich` console). Example output shown.
    - **Verbose mode**: `gencon-audiobook --verbose` enables DEBUG-level output. Explain what additional info appears (URLs fetched, CSS selectors matched, ffmpeg commands, file paths, timing).
    - **Log file**: The tool writes a full DEBUG-level log to `<output_dir>/gencon-audiobook.log` on every run. This file persists after the run completes and contains everything needed for troubleshooting.
    - **How to read the log file**: Explain the log format (`timestamp [LEVEL] module: message`), what each level means, and how to find the relevant section for a specific problem.
    - **Common troubleshooting scenarios** with "what to look for in the log":
      - "Scraper found 0 talks" → look for WARNING/ERROR about CSS selectors, check if HTML structure changed
      - "Download failed" → look for HTTP status codes, timeout messages, retry attempts
      - "ffmpeg error" → look for the exact ffmpeg command and its stderr output
      - "epub validation failed" → look for the specific epubcheck errors
    - **How to file a bug report**: Include the relevant log section (redacted if needed), Python version, OS, and tool version.

### Architecture Documentation (`docs/architecture.md`)

- Data flow diagram: website → scraper → models → downloader → audio/epub → output files
- Module responsibility diagram
- Error handling strategy (where errors are caught, how they're reported)
- Extensibility points for future features (multi-language, arbitrary conference, batch mode)

---

## Code Standards

### Logging

Use Python's standard `logging` module throughout. Industry-standard levels:

- **DEBUG**: Detailed diagnostic info (CSS selectors matched, URLs being fetched, file paths, ffmpeg commands). Only visible with `--verbose`.
- **INFO**: Key milestones the user should see (scraping started, download progress, conversion started, output files created). Shown by default via `rich` console handler.
- **WARNING**: Non-fatal issues (speaker photo missing, falling back to secondary CSS selector, retrying failed download).
- **ERROR**: Operation failures that can be recovered from (single file download failed after retries, single talk parsing failed — skip and continue).
- **CRITICAL**: Unrecoverable failures (no talks found, ffmpeg not available, output directory not writable).

Each module creates its own logger: `logger = logging.getLogger(__name__)`. The CLI configures the root logger level based on `--verbose` flag.

**Two output destinations:**
1. **Console** (via `rich`): INFO by default, DEBUG with `--verbose`. User-friendly formatting.
2. **Log file** (`<output_dir>/gencon-audiobook.log`): Always DEBUG level. Written on every run. Persists for troubleshooting. Contains full detail including URLs, ffmpeg commands, HTTP status codes, and timing.

**Format**: `%(asctime)s [%(levelname)s] %(name)s: %(message)s` for the log file. Rich-formatted for console.

### Comments

Follow the principle: **code says "what", comments say "why"**.

- **Module-level docstring** at the top of every `.py` file: one sentence describing the module's purpose.
- **Function/method docstrings**: Google-style docstrings for all public functions. Include `Args`, `Returns`, `Raises` sections. Type hints on all function signatures.
- **Inline comments**: Only for non-obvious logic — explain *why*, not *what*. Examples:
  - `# AAC-LC (not HE-AAC) for maximum Android compatibility` — good
  - `# Convert the file` — bad (obvious from code)
  - `# Fallback selector: site redesigned nav structure in 2024` — good
  - `# Parse the HTML` — bad
- **TODO comments**: Acceptable only for tracked future work with a GitHub issue reference: `# TODO(#42): Add multi-language support`
- **No commented-out code**: Delete it. Git has history.

### Type Hints

Full type annotations on all function signatures and class attributes. Use `from __future__ import annotations` for modern syntax. No `Any` unless genuinely unavoidable.

---

## Security Requirements

1. **URL allowlisting** — Only follow URLs to `churchofjesuschrist.org` and `*.ldscdn.org`. Reject any other domain. Log and skip unexpected URLs.
2. **Filename sanitization** — Strip/replace all characters outside `[a-zA-Z0-9 ._-]` from filenames. Prevent path traversal (`..`, absolute paths).
3. **SSL verification** — Always verify TLS certificates. Never disable. Never add `verify=False`.
4. **ffmpeg binary verification** — `static-ffmpeg` verifies hashes on download. Log binary path and version on first use.
5. **Rate limiting** — 0.5s delay between HTTP requests. User-Agent: `gencon-audiobook/<version> (open source; github.com/XeroIP/gencon-audiobook)`.
6. **Timeouts** — 30s connect, 120s read for MP3 downloads; 15s connect, 30s read for HTML pages. No infinite hangs.
7. **No secrets** — No credentials, API keys, or tokens anywhere. All scraped data is publicly accessible.
8. **Dependency auditing** — Pin major versions in pyproject.toml. Add `pip-audit` to CI.
9. **Input validation** — Validate all parsed URLs match expected patterns before fetching (e.g., MP3 URLs must match `https://*.ldscdn.org/*.mp3` or `https://media*.churchofjesuschrist.org/*`).
10. **No arbitrary code execution** — Never `eval()` or `exec()` scraped content. The site embeds base64-encoded JSON in page state; decode and parse JSON only, never execute.

---

## Phased Implementation

### Phase 1: Project Scaffolding + Scraper

**Prereq:** Repo `XeroIP/gencon-audiobook` already created in Step 0.

**Build:**
- `CLAUDE.md` at project root (see Claude Code Configuration section)
- `.claude/settings.json` with permissions for pytest, pip, build commands
- `.claude/rules/code-style.md`, `testing.md`, `security.md` (path-scoped rules)
- `.gitignore` (Python defaults + output directories + ffmpeg binaries + `*.m4b` + `*.epub` + `*.mp3` + `.claude/settings.local.json`)
- `pyproject.toml` with all metadata, entry points, dependencies, dev dependencies
- Full directory structure (all files, stubs where needed)
- `LICENSE` (MIT)
- `models.py` with Conference, Session, Talk dataclasses
- `scraper.py`:
  - `fetch_latest_conference_url()` → find most recent conference listing URL
  - `parse_conference_listing(html)` → list of Sessions with Talks (metadata only)
  - `parse_talk_page(html)` → extract mp3_url, transcript_html, speaker_image_url
  - `scrape_conference()` → orchestrate: fetch listing, parse talks, fetch each talk page, return Conference
  - Resilience: primary + fallback CSS selectors for key elements
  - Clear error messages when parsing fails
- `utils.py`: filename sanitizer, URL domain validator
- HTML snapshot fixtures saved from live site
- `test_scraper.py`: unit tests against fixtures (parse listing, parse talk page, handle missing elements)
- `test_scraper_live.py`: live smoke test (`@pytest.mark.live`)
- `test_utils.py`: sanitization edge cases (unicode, path traversal, empty strings, very long names)
- `scripts/update_fixtures.py`: fetch current HTML from live site, save to `tests/fixtures/`

**Phase 1 Test Plan (manual verification):**
```
1. cd gencon-audiobook && pip install -e ".[dev]"
2. pytest tests/test_scraper.py -v            # All pass against saved HTML fixtures
3. pytest tests/test_utils.py -v              # All pass
4. pytest tests/test_scraper_live.py -v       # Passes against live website
5. python -c "
   from gencon_audiobook.scraper import scrape_conference
   c = scrape_conference()
   print(f'{c.title}: {len(c.talks)} talks across {len(c.sessions)} sessions')
   for t in c.talks[:3]:
       print(f'  - {t.speaker}: {t.title}')
       print(f'    MP3: {t.mp3_url}')
       print(f'    Transcript length: {len(t.transcript_html or "")} chars')
   "
   # Expected: conference name, ~30-35 talks, each with title, speaker, mp3_url, transcript
6. Verify: no URLs point outside churchofjesuschrist.org or ldscdn.org
7. Verify: all talks have non-empty title, speaker, mp3_url, and transcript_html
8. python scripts/update_fixtures.py          # Verify fixture update script works
```

---

### Phase 2: Downloading (Audio + Images)

**Build:**
- `downloader.py`:
  - `download_file(url, dest, timeout, retries=3)` — exponential backoff, URL domain validation
  - `download_conference(conference, output_dir)` — download all MP3s, cover image, speaker photos
  - Skip already-downloaded files (check file exists + non-zero size)
  - Progress bars via `rich` (per-file and overall)
  - Convert all images to JPEG via Pillow (ensures epub/m4b compatibility)
- `test_downloader.py`: mocked HTTP tests (success, retry on 503, timeout, reject non-allowlisted URL, skip existing file)

**Phase 2 Test Plan:**
```
1. pytest tests/test_downloader.py -v         # All pass with mocked HTTP
2. Run scraper + downloader end-to-end:
   python -c "
   from gencon_audiobook.scraper import scrape_conference
   from gencon_audiobook.downloader import download_conference
   c = scrape_conference()
   download_conference(c, './test_output')
   "
3. ls -la ./test_output/                      # Verify directory structure
4. Verify: one MP3 per talk, all non-zero size
5. Verify: cover.jpg exists
6. Verify: speakers/ directory contains one JPEG per talk with speaker photo
7. Re-run step 2 — verify it skips all files (no re-download)
8. Delete one MP3, re-run — verify only the missing file is re-downloaded
9. Test network error: disconnect WiFi mid-download, verify:
   a. Clear error message (not a Python traceback)
   b. Partial files are cleaned up or resumable
```

---

### Phase 3: Audio Processing + m4b Creation

**Build:**
- `ffmpeg_manager.py`:
  - `ensure_ffmpeg()` → return path to ffmpeg binary, auto-downloading via `static-ffmpeg` if needed
  - Log ffmpeg version on first use
- `audio.py`:
  - `convert_mp3_to_aac(mp3_path, aac_path, ffmpeg_path)` — convert with: `-c:a aac -b:a 64k -ar 44100 -ac 1`
  - `build_m4b(conference, audio_dir, output_path, cover_path)`:
    - Concatenate AAC files in talk order
    - Embed chapter markers: chapter title = `"Talk Title — Speaker Name"`
    - Embed cover art as JPEG
    - Set metadata: title, artist="General Conference", album=conference title, year
  - Use `mutagen` to read/verify chapter markers and metadata after creation
- `test_audio.py`:
  - Generate short silent MP3 test fixtures programmatically
  - Test single-file conversion
  - Test m4b assembly with 3 fake chapters
  - Verify chapter metadata via mutagen (titles, timestamps, cover)

**Phase 3 Test Plan:**
```
1. pytest tests/test_audio.py -v              # All pass
2. Full pipeline — scrape, download, build m4b:
   gencon-audiobook --skip-epub --output ./test_output
3. Verify m4b file exists and has reasonable size (~100-200 MB for a full conference)
4. Play in VLC — verify audio plays correctly
5. Open in a player that shows chapters:
   - macOS: Apple Books or Podcasts app
   - Windows: iTunes
   - iOS: Apple Books → verify chapters list with "Title — Speaker" format
   - Android: Smart AudioBook Player → verify chapters list
6. Verify chapter count matches number of talks
7. Verify cover art displays
8. Verify: skipping between chapters lands at correct talk boundaries
9. Verify: total duration matches sum of individual MP3 durations (within 2s)
10. On a clean machine/venv: verify ffmpeg auto-downloads on first run
```

---

### Phase 4: Epub Companion

**Build:**
- `epub_builder.py`:
  - `build_epub(conference, images_dir, output_path)`:
    - EPUB 3.0, reflowable layout
    - Cover page with conference image (JPEG)
    - Table of contents with session groupings
    - Per-session section dividers
    - Per-talk chapters containing:
      - Speaker photo (JPEG, resized to max 300px wide)
      - Speaker name (as byline)
      - Talk title (as chapter heading)
      - Full transcript HTML (sanitized — strip scripts, external resources)
    - **Theme-safe CSS**: no hardcoded colors, fonts, or absolute sizes. Relative units only (`em`, `%`). Zero `color`, `background-color`, or `font-family` declarations. Reader themes (dark mode, sepia, custom fonts, large text, high contrast) must work automatically.
    - All images embedded as JPEG (no PNG for photos — avoids transparency issues on dark backgrounds)
- `test_epub.py`:
  - Validate epub structure with `ebooklib`
  - Verify all talks present
  - Verify images embedded
  - Verify no external URL references in content
  - Verify CSS contains no `color`, `background-color`, `font-family`, or `px`/`pt` font-size declarations
  - Verify all embedded images are JPEG

**Phase 4 Test Plan:**
```
1. pytest tests/test_epub.py -v               # All pass
2. Full pipeline including epub:
   gencon-audiobook --output ./test_output
3. Validate epub:
   java -jar epubcheck.jar "test_output/October 2024 General Conference.epub"
   # Must pass with 0 errors (warnings acceptable)
4. Open epub on each platform:
   - iOS: Apple Books → verify cover, TOC, chapters, speaker photos, transcript text
   - Android: Google Play Books → same checks
   - Android: Moon+ Reader → same checks
   - Kindle: Send to Kindle → verify conversion is clean, TOC works, images display
   - Desktop: Calibre → same checks
5. Verify content:
   a. Cover image displays on library/bookshelf view
   b. Table of contents navigates to correct chapters
   c. Each chapter shows: speaker photo, speaker name, talk title, full transcript
   d. Scripture references and paragraph formatting are preserved
   e. No broken images or placeholder text
6. Verify theme compatibility (on at least 2 different reader apps):
   a. Default/light theme → text and images render correctly
   b. Dark mode → text is readable, no white boxes around images, no invisible text
   c. Sepia/warm theme → text adapts to theme colors
   d. Change reader font → epub text uses the reader's chosen font
   e. Increase text size → layout remains intact, no text clipping or overflow
   f. If reader supports high-contrast/accessibility mode → verify it works
```

---

### Phase 5: CLI Polish + Packaging + CI/CD

**Build:**
- `cli.py`: Click-based CLI with:
  - `--output` directory option (default: `~/gencon-audiobook/`)
  - `--skip-epub` / `--skip-audiobook` flags
  - `--verbose` flag for debug logging
  - `--version` flag
  - Clean, user-friendly error messages for: no network, site changed, disk full, permission denied
  - `rich` console output: progress bars, status messages, final summary
- `README.md`:
  - Project description, referencing [original project](https://github.com/ChurchofJesusChristDev/General-Conference-to-Audiobook) as inspiration
  - Installation: `pip install gencon-audiobook`
  - Usage examples
  - Platform notes: Android users need Smart AudioBook Player or similar
  - Epub: works on Apple Books, Google Play Books, Kindle, Calibre, Moon+ Reader
  - Troubleshooting section
  - Contributing link
- `CONTRIBUTING.md`:
  - Dev setup instructions
  - How to run tests (unit, live, integration)
  - How to update scraper when website changes (step-by-step with `scripts/update_fixtures.py`)
  - PR requirements: tests pass, fixtures updated if scraper changed
- `docs/listening-guide.md`: personal device guide (see Documentation section)
  - Helps users open and use the downloaded files on each device type
  - Covers: what the files are, how to open them on every platform, tips for use
  - Code of conduct reference
- GitHub Actions:
  - `test.yml`: pytest on push/PR across Python 3.10, 3.11, 3.12, 3.13 × ubuntu, macos, windows
  - `publish.yml`: publish to PyPI on GitHub release tag (uses trusted publishing)
  - `live-test.yml`: weekly cron, runs live scraper test, opens GitHub issue on failure
- `.github/ISSUE_TEMPLATE/bug_report.md` and `website_changed.md`
- `docs/user-guide.md`: ELI5-level user documentation (see Documentation section above)
- `docs/technical-decisions.md`: Every technical decision with rationale (see Documentation section above)
- `docs/architecture.md`: Data flow diagram, module responsibilities, error handling strategy, extensibility points

**Phase 5 Test Plan:**
```
1. pytest --cov=gencon_audiobook --cov-report=term-missing   # Check coverage
2. pip install . && gencon-audiobook --help                   # CLI installs and runs
3. gencon-audiobook --version                                 # Shows version
4. gencon-audiobook                                           # Full end-to-end
5. gencon-audiobook --skip-epub                               # m4b only
6. gencon-audiobook --skip-audiobook                          # epub only
7. gencon-audiobook --verbose                                 # Detailed output
8. Error cases:
   a. Disconnect network → run → clear error message (not traceback)
   b. Set --output to read-only dir → clear error message
   c. Run with Python 3.9 → clear version requirement error
9. Cross-platform (all three):
   a. pip install gencon-audiobook (from PyPI or test.pypi.org)
   b. gencon-audiobook
   c. Verify both m4b and epub produced and functional
10. Push to GitHub → verify test.yml workflow passes on all matrix entries
11. Create a release tag → verify publish.yml triggers (test with test.pypi.org first)
12. Documentation review:
   a. Have a non-technical person follow docs/user-guide.md from scratch on a clean machine
   b. Verify every step works without external help
   c. Verify docs/technical-decisions.md covers all decisions from this plan
   d. Verify docs/architecture.md matches actual implementation
   e. Follow docs/listening-guide.md yourself on each device type (iOS, Android, desktop)
      — can you open and use the files using only the guide? No confusion = pass.
   f. Verify LICENSE-CONTENT.md is present and clearly distinguishes tool license from content copyright
   g. Verify README disclaimer is prominent and accurate
```

---

## Testing Strategy for Website Changes

This is the most critical ongoing concern. The Church website **will** change.

1. **Fixture-based unit tests** (`test_scraper.py`) — Parse saved HTML snapshots. Fast, deterministic, document what the scraper expects. When the site changes, update fixtures first, then fix the scraper.

2. **Live smoke test** (`test_scraper_live.py`) — Hit the real site, verify we get a Conference with 30+ talks, each with MP3 URL and transcript. Marked `@pytest.mark.live`, skipped in normal CI.

3. **Weekly CI cron job** (`live-test.yml`) — Auto-run the live smoke test. On failure, create a GitHub issue: "Website structure may have changed" with error details. Early warning before users report it.

4. **Resilience in the scraper:**
   - Primary + fallback CSS selectors for key elements
   - Validate parsed data shapes (Talk must have title, speaker, MP3 URL)
   - Descriptive error messages: "Could not find talk listings. The website structure may have changed. Please open a GitHub issue at <url>."

5. **Fixture update script** (`scripts/update_fixtures.py`) — Fetches current HTML from the live site and saves to `tests/fixtures/`. Run this when the site changes to update test baselines.

---

## Verification (End-to-End)

After all phases are complete, the following should work on a clean machine with only Python 3.10+ installed:

```bash
pip install gencon-audiobook
gencon-audiobook
# Output:
#   Fetching latest General Conference...
#   Found: October 2024 General Conference (34 talks)
#   Downloading audio... ━━━━━━━━━━━━━━━━━━━━ 34/34
#   Downloading images... ━━━━━━━━━━━━━━━━━━━━ 35/35
#   Building audiobook... ━━━━━━━━━━━━━━━━━━━━ done
#   Building epub... ━━━━━━━━━━━━━━━━━━━━ done
#
#   ✓ October 2024 General Conference.m4b (187 MB, 34 chapters)
#   ✓ October 2024 General Conference.epub (12 MB, 34 talks with transcripts)
#   Saved to: ~/gencon-audiobook/October 2024 General Conference/
```

# gencon-audiobook

[![CI](https://github.com/XeroIP/gencon-audiobook/actions/workflows/ci.yml/badge.svg)](https://github.com/XeroIP/gencon-audiobook/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/gencon-audiobook)](https://pypi.org/project/gencon-audiobook/)
[![Python versions](https://img.shields.io/pypi/pyversions/gencon-audiobook)](https://pypi.org/project/gencon-audiobook/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Download General Conference talks from [churchofjesuschrist.org](https://www.churchofjesuschrist.org) and produce:

- A **chaptered `.m4b` audiobook** — one chapter per talk, with speaker name in the chapter title, cover art, and full metadata
- An **`.epub` companion** — full transcripts, speaker photos, nested session/talk table of contents, and theme-safe CSS (dark mode, sepia, and accessibility modes all work)

Single `pip install`, no prerequisites beyond Python 3.10+. ffmpeg is located automatically — on your PATH if present, otherwise downloaded once via `static-ffmpeg`.

Inspired by [General-Conference-to-Audiobook](https://github.com/ChurchofJesusChristDev/General-Conference-to-Audiobook).

> **Disclaimer:** This is an unofficial tool not affiliated with The Church of Jesus Christ of Latter-day Saints. General Conference content is copyright Intellectual Reserve, Inc. All rights reserved. This tool downloads content for personal, noncommercial use as permitted by the Church's Terms of Use.

---

## Installation

```bash
pip install gencon-audiobook
```

Python 3.10 or newer is required. All other dependencies, including ffmpeg, are handled automatically. ffmpeg 1.0+ is required for per-file progress display during conversion; any ffmpeg from a package manager or the `static-ffmpeg` fallback exceeds this.

New to the terminal or Python? See the [User Guide](https://github.com/XeroIP/gencon-audiobook/wiki/User-Guide) for step-by-step instructions.

---

## Usage

```bash
# Download the most recent conference (both audiobook and epub)
gencon-audiobook

# Select a specific conference
gencon-audiobook --conference "April 2024"

# Audiobook only (skip epub)
gencon-audiobook --audiobook-only

# EPUB only (skip audiobook and audio download)
gencon-audiobook --epub-only

# Custom output directory
gencon-audiobook --output ~/Books

# Rebuild existing output files
gencon-audiobook --overwrite

# Reduce file size (lower bitrate and sample rate)
gencon-audiobook --bitrate 32k --sample-rate 22050

# Show detailed progress in the terminal
gencon-audiobook --verbose
```

For the full options reference, file size guide, and platform compatibility notes, see the [User Guide](https://github.com/XeroIP/gencon-audiobook/wiki/User-Guide).

---

## Output structure

```
~/gencon-audiobook/
  April 2024 General Conference/
    April 2024 General Conference.m4b    # Chaptered audiobook
    April 2024 General Conference.epub   # Transcript companion
    cover.jpg                            # Conference cover image
    audio/                               # Downloaded MP3 files
    speakers/                            # Speaker photos
    gencon-audiobook.log                 # Full DEBUG log for troubleshooting
```

Running the tool a second time skips files that already exist. Use `--overwrite` to rebuild.

---

## Documentation

- [User Guide](https://github.com/XeroIP/gencon-audiobook/wiki/User-Guide) — full options reference, file size guide, platform support, troubleshooting
- [Listening/Reading Guide](https://github.com/XeroIP/gencon-audiobook/wiki/Listening-Reading-Guide) — how to open the output files on every platform
- [Architecture](https://github.com/XeroIP/gencon-audiobook/wiki/Architecture) — codebase structure for contributors
- [Technical Decisions](https://github.com/XeroIP/gencon-audiobook/wiki/Technical-Decisions) — design choices with rationale

---

## Development

```bash
git clone https://github.com/XeroIP/gencon-audiobook.git
cd gencon-audiobook
pip install -e ".[dev]"

# Run unit tests (no network required)
pytest tests/ --ignore=tests/test_scraper_live.py --ignore=tests/test_integration.py

# Run live smoke tests (hits the real website)
pytest tests/test_scraper_live.py -v -m live

# Run full end-to-end integration test (requires ffmpeg)
pytest tests/test_integration.py -v -m integration
```

### Project layout

```
src/gencon_audiobook/
  cli.py            Click entry point
  scraper.py        Fetch and parse conference listings and talk pages
  downloader.py     Download MP3s, cover, and speaker photos
  audio.py          Convert MP3 to AAC, assemble chaptered m4b
  epub_builder.py   Build EPUB 3 ZIP from transcripts and images
  ffmpeg_manager.py Locate ffmpeg/ffprobe (PATH first, static-ffmpeg fallback)
  models.py         Conference / Session / Talk dataclasses
  utils.py          sanitize_filename(), validate_url()

tests/
  conftest.py             Shared helpers (ffmpeg discovery, silent MP3, JPEG)
  test_scraper.py         Unit tests against saved HTML fixtures
  test_downloader.py      Mocked HTTP tests
  test_audio.py           Audio pipeline with generated silent fixtures
  test_epub.py            EPUB structure and content validation
  test_cli.py             CLI behavior (all external calls mocked)
  test_utils.py           Filename sanitization and URL validation
  test_ffmpeg_manager.py  ffmpeg/ffprobe discovery and caching
  test_scraper_live.py    Live smoke tests (@pytest.mark.live)
  test_integration.py     End-to-end test (@pytest.mark.integration)
  fixtures/               Saved HTML snapshots for scraper unit tests
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Legal

- **Tool license:** MIT — see [LICENSE](LICENSE)
- **Downloaded content:** Copyright Intellectual Reserve, Inc. — see [LICENSE-CONTENT.md](LICENSE-CONTENT.md)

This tool accesses publicly available content using a transparent User-Agent string, respects `robots.txt`, and applies a rate-limiting delay between requests. It is intended for personal, noncommercial use only.

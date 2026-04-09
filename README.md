# gencon-audiobook

[![CI](https://github.com/XeroIP/gencon-audiobook/actions/workflows/ci.yml/badge.svg)](https://github.com/XeroIP/gencon-audiobook/actions/workflows/ci.yml)

Download General Conference talks from [churchofjesuschrist.org](https://www.churchofjesuschrist.org) and produce:

- A **chaptered `.m4b` audiobook** — one chapter per talk, with speaker name in the chapter title, cover art, and full metadata
- An **`.epub` companion** — full transcripts, speaker photos, nested session/talk table of contents, and theme-safe CSS (dark mode, sepia, and accessibility modes all work)

Single `pip install`, no prerequisites beyond Python 3.10+. ffmpeg is located automatically — on your PATH if present, otherwise downloaded once via `static-ffmpeg`.

> **Disclaimer:** This is an unofficial tool. It is not affiliated with, endorsed by, or sponsored by The Church of Jesus Christ of Latter-day Saints. Downloaded content is copyright Intellectual Reserve, Inc. and is permitted for personal, noncommercial use per the Church's Terms of Use.

---

## Installation

```bash
pip install gencon-audiobook
```

Python 3.10 or newer is required. All other dependencies, including ffmpeg, are handled automatically.

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

### All options

| Option | Default | Description |
|---|---|---|
| `--output DIR` | `~/gencon-audiobook` | Directory to save output files |
| `--conference TEXT` | Most recent | Conference to download, e.g. `"April 2024"` |
| `--audiobook-only` | off | Produce only the m4b, skip epub |
| `--epub-only` | off | Produce only the epub, skip audiobook |
| `--overwrite` | off | Rebuild existing output files instead of skipping |
| `--bitrate TEXT` | `64k` | AAC encoding bitrate (e.g. `32k`, `48k`, `64k`) |
| `--sample-rate INT` | `44100` | Audio sample rate in Hz (e.g. `22050`, `44100`) |
| `--verbose` | off | Enable DEBUG-level console output |
| `--version` | | Show version and exit |

### File size guide

The defaults (64k / 44.1 kHz) produce a ~190 MB audiobook for a full conference.

| Bitrate | Sample rate | Approximate size | Notes |
|---|---|---|---|
| 64k | 44100 | ~190 MB | Default — good quality for speech |
| 48k | 44100 | ~145 MB | Slightly smaller, imperceptible difference |
| 32k | 22050 | ~80 MB | Noticeably lower fidelity, fine for speech |

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

## Platform support

### Audiobook (m4b)

| Platform | App | Notes |
|---|---|---|
| iOS | Apple Books, Overcast, Bound, BookPlayer | Native support, chapters work |
| Android | Smart AudioBook Player, Sirin Audiobook Player | The default music app and Google Play Books do **not** support m4b — a dedicated audiobook app is required |
| macOS | Apple Books, VLC | Apple Books shows chapters; VLC plays audio but ignores chapters |
| Windows | iTunes / Apple Music, VLC | Same as macOS |

### EPUB

| Platform | App | Notes |
|---|---|---|
| iOS / macOS | Apple Books | Native support |
| Android | Google Play Books, Moon+ Reader, ReadEra | Google Play Books is built in |
| Kindle | Send to Kindle | Amazon auto-converts epub to AZW3 |
| Desktop | Calibre, Thorium Reader | Calibre is the reference tool for validation |

---

## Disk space

Approximately **500 MB** of working space is needed during a full download and build:

- MP3 downloads: ~250 MB
- Finished m4b: ~190 MB
- Finished epub: ~15 MB

Downloaded files persist after the build. Running with `--audiobook-only` or `--epub-only` reduces peak disk usage.

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

# Coverage report
pytest --cov=gencon_audiobook --cov-report=term-missing
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
  test_scraper.py         Unit tests against saved HTML fixtures
  test_downloader.py      Mocked HTTP tests
  test_audio.py           Audio pipeline with generated silent fixtures
  test_epub.py            EPUB structure and content validation
  test_cli.py             CLI behavior (all external calls mocked)
  test_utils.py           Filename sanitization and URL validation
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

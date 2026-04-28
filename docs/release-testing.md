# Release Testing Guide

How to smoke-test a published PyPI release end-to-end. Run this after tagging a new version
and before announcing it, using the version installed from PyPI — not from source.

## Prerequisites

- Python 3.10+
- ffmpeg on PATH (or `static-ffmpeg` installed) — required for the full audiobook run only
- ~500 MB free disk space for a full conference download
- Internet access to `churchofjesuschrist.org`

---

## Step 1: Install from PyPI into a clean environment

Do not use your dev venv. A clean venv proves the package installs correctly with no
dependency on local source changes.

```bash
python -m venv test-release
# Windows:
test-release\Scripts\activate
# Mac/Linux:
source test-release/bin/activate

pip install gencon-audiobook==0.1.8   # replace with the version being tested
```

Verify the entry point and version:

```bash
gencon-audiobook --version
gencon-audiobook --help
```

---

## Step 2: Quick pass — epub only (no ffmpeg, ~2 min)

The epub-only pass covers scraping, image downloading, HTML sanitization, and EPUB assembly
without needing ffmpeg or a 200 MB MP3 download. Run this first.

```bash
gencon-audiobook --epub-only --conference 2024-04 --output ~/gc-test
```

**What to check:**

- Command exits 0 with a completion report printed
- `~/gc-test/April 2024 General Conference/April 2024 General Conference.epub` exists and is 10–20 MB
- Open the epub in Calibre, Apple Books, or your reader and verify:
  - Cover page displays as portrait (taller than wide) in the library grid
  - Copyright page (Intellectual Reserve, Inc.)
  - Navigable TOC with session headings and talk entries
  - Session headings in the TOC link to session divider pages (not directly to the first talk)
  - Landmarks nav visible in Calibre's TOC panel (cover, TOC, Start of Content entries)
  - Per-talk chapters with speaker photo, name byline, and full transcript
  - Footnote numbers visible inline (not blank superscripts)
  - No garbled text (mojibake) in speaker names or talk titles
  - No web CSS class names visible as raw text in transcripts

---

## Step 3: Full run — audiobook + epub (~30–60 min)

```bash
gencon-audiobook --conference 2024-04 --output ~/gc-test --overwrite
```

**What to check in the completion report:**

- Duration reported as approximately 2 hours for a typical conference
- Chapter count matches the number of talks (~31 for April 2024)
- Source and output audio quality lines look reasonable (e.g. `64k / 22050 Hz`)
- File size for the m4b is in the 150–250 MB range

**What to check in the m4b:**

Open `~/gc-test/April 2024 General Conference/April 2024 General Conference.m4b` in a
chapter-aware player (Prologue, Bound, Overcast, VLC):

- Chapter list shows all talk titles, no blank or duplicate entries
- Scrub to several chapters mid-file and confirm audio starts at the right talk,
  not mid-previous-talk (timing alignment check)
- Speaker names in chapter titles display correctly — no mojibake or `?` substitutions

---

## Step 4: Check the log for unexpected warnings

```bash
# Windows:
type "%USERPROFILE%\gc-test\April 2024 General Conference\gencon-audiobook.log" | findstr /i "warning error critical"

# Mac/Linux:
grep -i "warning\|error\|critical" ~/gc-test/"April 2024 General Conference"/gencon-audiobook.log
```

A clean run has no ERROR or CRITICAL lines. WARNING lines are acceptable for minor issues
(e.g. a single speaker photo missing), but should not appear for every talk.

---

## Step 5: Cleanup

```bash
deactivate
rm -rf test-release
rm -rf ~/gc-test
```

---

## Common failure points

| Symptom | Likely cause |
|---|---|
| `ScraperError` on startup | Site HTML structure changed since last fixture update |
| Talks missing from epub/m4b | MP3 URLs changed format or are temporarily unavailable |
| Mojibake in chapter titles | Non-ASCII character in a speaker name or talk title hitting an encoding edge case |
| Chapter audio misaligned | Duration detection failed for one or more talks; check WARNING lines in the log |
| `FfmpegNotFoundError` | ffmpeg not on PATH and `static-ffmpeg` not installed; install either |
| epub fails epubcheck | EPUB structure regression; run `epubcheck` on the output file for details |

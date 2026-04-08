# Phase 3: CLI Polish

## Objective

Make the CLI production-quality. Every failure mode must produce a clear, actionable message
without a Python traceback reaching the user. Logging must be properly configured with dual
output (rich console + persistent log file).

Refer to `docs/spec.md` and `.claude/rules/code-style.md`.

---

## Prerequisites

- Phase 2 complete: both m4b and epub produced correctly
- `gencon-audiobook` works end-to-end but error handling is basic

---

## Step 1: Error Handling in `cli.py`

Wrap all pipeline steps in appropriate error handling. The user must never see a Python traceback.

### Error message format

```
Error: <what failed>
<specific detail if available>

<what to try next>
```

No emojis. No "Traceback (most recent call last)".

### Specific error cases to handle

| Failure | User message |
|---|---|
| No network / DNS failure | "Could not connect to churchofjesuschrist.org. Check your internet connection and try again." |
| Website blocking (Cloudflare/403) | "Access was blocked by the website. This may be temporary. Wait a few minutes and try again, or open a GitHub issue if this persists: github.com/XeroIP/gencon-audiobook" |
| Website structure changed (0 talks) | "Could not find any talks on the conference page. The website may have changed. Please open a GitHub issue: github.com/XeroIP/gencon-audiobook" |
| Disk full during download | "Not enough disk space to download. Free up space and run again — previously downloaded files will not need to be re-downloaded." |
| Output directory not writable | "Cannot write to {path}. Check permissions and try again." |
| ffmpeg not available and download failed | (Use FfmpegNotFoundError message from ffmpeg_manager.py — it already contains install instructions) |
| Python version too old (< 3.10) | Check at CLI entry point: "This tool requires Python 3.10 or newer. You are running Python {version}. Please upgrade: python.org/downloads" |
| Keyboard interrupt (Ctrl+C) | "Download interrupted. Run again to resume — already-downloaded files will not be re-downloaded." |

### `--verbose` flag

When `--verbose` is set:
- Set root logger to DEBUG level
- Show DEBUG messages in the rich console
- Useful for troubleshooting scraper issues

---

## Step 2: Dual Logging

Configure two log destinations in `cli.py` before any pipeline work begins:

### Console handler (rich)
- Level: INFO by default, DEBUG with `--verbose`
- Format: just the message (rich handles visual formatting)
- Handler: `rich.logging.RichHandler`

### File handler
- Level: always DEBUG
- File: `<output_dir>/gencon-audiobook.log`
- Format: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`
- Mode: write (overwrite on each run — keeps the log fresh)
- Create the output directory before creating the log file

### Setup

```python
import logging
from rich.logging import RichHandler

def setup_logging(output_dir: Path, verbose: bool) -> None:
    """Configure dual logging: rich console + debug log file."""
    log_level = logging.DEBUG if verbose else logging.INFO

    # Rich console handler
    console_handler = RichHandler(
        level=log_level,
        show_time=False,
        show_path=False,
        markup=False,
    )

    # File handler — always DEBUG
    log_file = output_dir / "gencon-audiobook.log"
    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    logging.basicConfig(
        level=logging.DEBUG,  # root at DEBUG; handlers filter
        handlers=[console_handler, file_handler],
        force=True,
    )
```

---

## Step 3: Disk Space Check

Before starting the download, check available disk space:

```python
import shutil

def check_disk_space(output_dir: Path, required_mb: int = 500) -> None:
    """Warn if available disk space is below required_mb."""
    stat = shutil.disk_usage(output_dir)
    available_mb = stat.free // (1024 * 1024)
    if available_mb < required_mb:
        # Not a hard failure — warn and let user decide
        console.print(
            f"[yellow]Warning:[/yellow] Only {available_mb} MB available in {output_dir}. "
            f"This tool requires approximately {required_mb} MB. "
            "Proceed with caution."
        )
```

Always print the disk space note before download begins:
```
Note: approximately 500 MB of disk space is required for a full conference.
```

---

## Step 4: Progress and Summary Output

### During pipeline

Use `rich` for all user-facing output. No print() calls outside of rich. No emojis.

Standard flow:
```
Fetching available conferences...
Found 52 conferences. Using: April 2024 General Conference (34 talks)

Note: approximately 500 MB of disk space is required.

Downloading audio (34 files)...  [##########] 34/34
Downloading images (35 files)... [##########] 35/35

Building audiobook...
Building epub...

Output saved to: /home/user/gencon-audiobook/April 2024 General Conference/
  April 2024 General Conference.m4b  (187 MB, 34 chapters)
  April 2024 General Conference.epub (12 MB, 34 talks)
```

If any talks were skipped (download failures):
```
Warning: 2 talks could not be downloaded and are not included in the output.
  - Talk Title 1 (Speaker Name)
  - Talk Title 2 (Speaker Name)
For details, see: /path/to/gencon-audiobook.log
```

### Log file reference on error

Whenever a non-fatal error or warning is shown, append:
```
For details, see: <output_dir>/gencon-audiobook.log
```

---

## Step 5: Edge Cases

Handle gracefully (no traceback):

- **Zero valid talks after scraping**: ScraperError with clear message (already in scraper,
  just ensure cli.py catches and displays it cleanly)
- **All downloads fail**: After download phase, if zero MP3s exist, abort with clear message
  before attempting ffmpeg work
- **Partial downloads (some talks missing)**: Continue building with available talks; list
  skipped talks in final summary
- **Conference already downloaded**: Detect that output files already exist and ask user whether
  to overwrite or skip. Default: skip (print message explaining, add `--overwrite` flag)
- **Conference selection**: If `--conference` value doesn't match any available conference,
  print the list of available conferences and exit with a helpful message

---

## Phase 3 Test Plan

```bash
# 1. Error handling tests
# Disconnect network, run:
gencon-audiobook
# Expected: "Could not connect..." message, no traceback, exit code 1

# 2. Permission error
mkdir /tmp/readonly_test && chmod 444 /tmp/readonly_test
gencon-audiobook --output /tmp/readonly_test
# Expected: "Cannot write to..." message, no traceback

# 3. Verbose mode
gencon-audiobook --verbose --audiobook-only --output ./test_output
# Expected: DEBUG-level output visible in console

# 4. Log file
gencon-audiobook --audiobook-only --output ./test_output
ls -la ./test_output/<conference>/gencon-audiobook.log
# Expected: log file exists, contains timestamps and log levels

# 5. Already downloaded
gencon-audiobook --output ./test_output  # second run
# Expected: "Output files already exist. Use --overwrite to replace them."

# 6. Invalid conference name
gencon-audiobook --conference "Fake Conference 9999"
# Expected: lists available conferences, clean error message

# 7. Disk space warning
# (Hard to test without filling disk — verify the logic in code review)

# 8. Keyboard interrupt
# Start download, press Ctrl+C
# Expected: "Download interrupted. Run again to resume..." message
```

**Exit criteria**: Every documented failure mode produces a clean message. No traceback reaches
the user in any scenario. Log file is always created and contains DEBUG-level detail.

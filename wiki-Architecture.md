# Architecture

This page describes the structure of the codebase for contributors and developers.

---

## Data flow

```
churchofjesuschrist.org
        |
        v
  [ scraper.py ]
  Fetch conference archive -> parse ConferenceRef list
  Fetch conference listing -> parse Session/Talk stubs
  Fetch each talk page    -> extract mp3_url, transcript_html,
                             speaker_image_url, inline_images, speaker name
        |
        v
  [ cache.py ]
  Save Conference to conference.json after first scrape.
  Load from conference.json on subsequent runs (skips scraping).
  --force-scrape bypasses the cache.
        |
        v
  [ models.py ]
  Conference(title, year, month, sessions, cover_image_url)
    Session(name, number, talks)
      Talk(title, speaker, mp3_url, transcript_html,
           speaker_image_url, inline_images, talk_index, session_name, ...)
        |
        v
  [ downloader.py ]
  Images (parallel, up to 8 threads):
    Download cover      -> cover.jpg
    Download photos     -> speakers/{index}-{speaker}.jpg
    Download body imgs  -> inline/{index}-{asset_id}.jpg
  Audio (sequential, 0.5s delay):
    Download MP3s       -> audio/{index}-{title}.mp3
  (JPEG conversion applied to all images via Pillow)
  (resume: skips files already at correct size)
        |
        +---------------------------+
        |                           |
        v                           v
  [ audio.py ]               [ epub_builder.py ]
  Probe source quality        Sanitize transcripts
  MP3 -> AAC-LC (ffmpeg)      Resize speaker photos (IIIF 800px -> 300px embed)
  Write FFMETADATA1           Compose portrait cover (landscape -> 1200x1800 canvas)
  Concat AAC files            Embed inline body images
  Mux chapters + cover        Assemble EPUB 3 ZIP:
  Verify with mutagen           mimetype (ZIP_STORED)
  Delete intermediate .m4a      META-INF/container.xml
        |                        content.opf
        v                        nav.xhtml (toc + landmarks)
  output.m4b                     style.css
                                 text/cover.xhtml
                                 text/copyright.xhtml
                                 text/session-NNN-*.xhtml
                                 text/talk-NNN-*.xhtml
                                 images/cover.jpg (ZIP_STORED)
                                 images/spk-NNN-*.jpg (ZIP_STORED)
                                 images/inline-NNN-*.jpg (ZIP_STORED)
                                 |
                                 v
                            output.epub
```

ffmpeg is located by `ffmpeg_manager.py` before either audio pipeline starts.

---

## Module responsibilities

### `cli.py`

The Click entry point. Parses CLI arguments, orchestrates the pipeline, and handles user-facing output.

Responsibilities:
- Configure console logging (Rich handler) and file logging
- Validate Python version and warn on low disk space
- Call `fetch_available_conferences()` and present a selection
- Call `scrape_conference()` to get the full Conference object
- Call `download_conference()` and surface any failed talks
- Call `build_m4b()` and `build_epub()` based on `--audiobook-only` / `--epub-only` flags
- Print the completion summary

The `main()` function is thin: it calls `_run()` and wraps it in a `KeyboardInterrupt` handler. All logic lives in `_run()` and the helper functions `_setup_logging`, `_add_file_logging`, `_check_python_version`, `_check_disk_space`, and `_select_conference`.

### `scraper.py`

Fetches and parses all conference data from the Church website.

Public API: `fetch_available_conferences() -> list[ConferenceRef]`, `scrape_conference(url) -> Conference`

Two-layer parsing strategy for resilience against site changes:
1. **Primary:** Extract `window.__INITIAL_STATE__` (base64-encoded JSON embedded in a `<script>` tag). This is structured and stable.
2. **Fallback:** BeautifulSoup HTML traversal. Triggered when the JSON selector finds nothing and logged as a WARNING.

After extracting the main talk body (`div.body-block`), the scraper also checks for a sibling `<footer class="notes">` element and appends its HTML to `transcript_html`. This is necessary because footnote bodies on Church talk pages live outside `div.body-block` and would otherwise be discarded.

HTTP behavior: `requests.Session` with custom User-Agent, explicit timeouts, exponential backoff retry on transient errors, robots.txt compliance check, and 4-priority encoding detection for multi-language resilience.

Depends on: `models.py`, `utils.py` (for `validate_url`)

### `downloader.py`

Downloads all files for a conference: MP3 audio, conference cover image, speaker photos, and inline body images.

Public API: `download_conference(conference, output_dir, delay, skip_audio) -> list[Talk]`

The returned list contains talks whose audio download failed -- these are surfaced to the user as warnings after the build. All other failures (images) are logged but do not affect the return value.

Download behavior: atomic `.tmp` + rename, resume by Content-Length comparison, exponential backoff retry. Images are converted to JPEG via Pillow before saving (handles PNG, WebP, and other formats from the Church CDN). Progress is shown with a Rich progress bar.

Images (cover, speaker photos, inline body images) download in parallel using `ThreadPoolExecutor` with up to 8 workers. Each worker thread gets its own `requests.Session` via `threading.local` (`_get_thread_session()`). MP3 audio downloads remain sequential with a 0.5s courtesy delay.

Depends on: `models.py`, `utils.py`

### `audio.py`

Converts downloaded MP3 files to AAC and assembles the chaptered m4b audiobook.

Public API: `build_m4b(conference, audio_dir, output_path, cover_path, ffmpeg_path, ffprobe_path, bitrate, sample_rate)`, `convert_mp3_to_aac(mp3_path, aac_path, ffmpeg_path, bitrate, sample_rate) -> float`

Pipeline inside `build_m4b`:
1. Probe the first available MP3 with ffprobe to detect source bitrate/sample rate (unless `--bitrate`/`--sample-rate` were passed explicitly)
2. Convert each MP3 to AAC-LC mono (`-vn` strips embedded cover art that would cause container errors)
3. Write an FFMETADATA1 chapter file with millisecond-precision chapter boundaries
4. Concatenate all AAC files using the ffmpeg concat demuxer
5. Mux the concatenated AAC, chapter metadata, and optional cover art into the m4b
6. Delete intermediate `.m4a` files
7. Verify with mutagen (cover art present) and ffprobe (chapter count and title format)

Chapter titles are ASCII-safe (`_ascii_safe()`) to avoid ffmpeg codepage/UTF-8 conflicts on Windows. Format is `"Talk Title -- Speaker Name"`.

Depends on: `models.py`, `utils.py`, ffmpeg and ffprobe binaries

### `epub_builder.py`

Builds an EPUB 3 companion with transcripts, speaker photos, inline images, session divider pages, and a nested table of contents.

Public API: `build_epub(conference, images_dir, output_path)`

Assembles a ZIP archive directly (no ebooklib). The `mimetype` entry is always first and stored uncompressed (`ZIP_STORED`), as required by the EPUB specification. All JPEG images are also stored with `ZIP_STORED` to avoid the double-compression problem (JPEG is already compressed; DEFLATE adds negligible size reduction but causes bugs on some older e-ink readers).

Speaker photos are fetched at 800px via IIIF URL rewriting, then resized to at most 300px wide before embedding. The landscape cover image is centered on a 1200x1800 gray canvas to produce a proper 2:3 portrait cover. Inline body images from talk pages are downloaded to `inline/` and embedded in the EPUB.

Transcripts are sanitized via BeautifulSoup: `<script>`, `<style>`, `<iframe>` tags removed; external `href`/`src` stripped; web CSS class names and `data-*` attributes removed. Footnote superscript links are detected via `class="note-ref"` + `data-scroll-id` (the Church site generates full talk-page URLs, not bare `#noteN` fragments); they are normalised to bare fragment hrefs and marked `epub:type="noteref"`. Footnote body elements (`<li id="noteN">` in `footer.notes`, matching `^note\d+$`) are wrapped in `<aside epub:type="footnote">` for popup support in Apple Books, Kobo, and Thorium.

Session divider pages (`text/session-NNN-*.xhtml`) are included so TOC session headers link to a unique destination. EPUB landmarks navigation (`<nav epub:type="landmarks">`) is included with cover, TOC, and bodymatter entries.

CSS is theme-safe: zero `color`, `background-color`, or `font-family` declarations. All visual styling is deferred to the reader application. (Note: two `font-size` declarations using relative `em` units currently exist and are tracked for removal; see Technical Decisions section 5 for details.)

A post-write ZIP integrity check (`testzip()`) runs after the EPUB is assembled and raises `EpubError` if any entry is corrupt.

Depends on: `models.py`, `utils.py`, Pillow for image resizing and canvas composition, BeautifulSoup for transcript sanitization

### `ffmpeg_manager.py`

Locates ffmpeg and ffprobe, downloading via `static-ffmpeg` if they are not on the system PATH.

Public API: `ensure_ffmpeg() -> Path`, `ensure_ffprobe() -> Path`, `reset_cache()` (testing only)

Search order for ffmpeg:
1. `shutil.which("ffmpeg")` -- system PATH
2. `static_ffmpeg.add_paths()` -- automatic download

ffprobe is located by looking next to the ffmpeg binary (same directory, same `.exe` suffix on Windows), then falling back to PATH. Both paths are cached after the first call.

Depends on: `static-ffmpeg` package (optional, only imported if ffmpeg is not on PATH)

### `models.py`

Data classes for the domain model.

- `Conference(title, year, month, cover_image_url, sessions, conference_url)` -- top-level container
- `Session(name, number, talks)` -- a single conference session
- `Talk(title, speaker, talk_url, mp3_url, transcript_html, speaker_image_url, inline_images, session_name, session_number, talk_number, talk_index, duration_seconds)` -- a single talk with all metadata
- `InlineImage(url, asset_id)` -- a single inline body image referenced in a talk's transcript

`talk_index` is a 1-based integer across the whole conference (not per-session). It is used as the numeric prefix in filenames (`001-`, `002-`, etc.) to ensure stable ordering. `duration_seconds` starts at 0.0 and is set by `audio.py` during MP3-to-AAC conversion. `inline_images` is populated by `scraper.py` from `<img>` tags in the talk transcript (srcset parsed for largest resolution).

`Conference.talks` is a convenience property that returns all talks from all sessions in order.

### `cache.py`

Serializes and deserializes `Conference` objects to/from `conference.json` in the output directory.

Public API: `save_conference(conference, path)`, `load_conference(path) -> Conference | None`

The JSON file uses the same structure as the `Conference` dataclass. A `cache_version` field allows future format changes to invalidate stale caches automatically. `load_conference` returns `None` (cache miss) if the file is absent, unreadable, or from an incompatible version.

Used by `cli.py`: after scraping, the Conference is saved. On the next run, `cli.py` loads from cache and skips scraping entirely. `--force-scrape` bypasses this and scrapes fresh data regardless.

Depends on: `models.py`

### `progress.py`

Custom Rich progress column for the time-remaining display.

Contains `TimeRemainingWithLabel`, a `rich.progress.TimeRemainingColumn` subclass that appends a "remaining" label and supports a `compact` mode for narrower terminals.

Used by: `downloader.py`, `audio.py`, `epub_builder.py`

### `utils.py`

Two utility functions used across multiple modules.

`sanitize_filename(name) -> str`: Replaces characters outside `[a-zA-Z0-9 ._-]` with underscores, collapses consecutive underscores, strips leading/trailing underscores and dots, truncates to 200 characters, and rejects path traversal patterns. Returns `"unnamed"` for empty or entirely-unsafe inputs.

`validate_url(url) -> bool`: Returns True only if the URL hostname matches the allowlist (`churchofjesuschrist.org`, `*.churchofjesuschrist.org`, `*.ldscdn.org`). Never raises -- malformed URLs return False.

---

## Error handling strategy

### Where errors propagate vs. are caught

**Unrecoverable errors abort the run** with a user-facing message:
- `ScraperError`: Conference page unreachable, no talks found, access blocked
- `DownloadError` (raised from `download_conference`): Only if the entire download system fails (individual talk failures are collected and reported, not raised)
- `FfmpegNotFoundError`: ffmpeg cannot be located or downloaded
- `AudioError`: ffmpeg step fails (the m4b cannot be partially assembled)
- `EpubError`: Output file cannot be written

**Recoverable errors skip the affected item and continue:**
- A single talk page fails to scrape: logged at ERROR, talk is marked as skipped, scraping continues
- A single MP3 download fails: logged at ERROR, talk is added to `failed_talks`, download continues, warning shown at end
- A single speaker photo fails to download: logged at ERROR, photo is absent from epub, not fatal
- A single AAC conversion fails: logged at ERROR, talk is skipped from the m4b (chapter count will be lower than expected)
- A single speaker photo fails to embed in the EPUB: logged at WARNING, photo is absent

### Retry strategy

Both the scraper and downloader use exponential backoff:
- Attempt 0: immediate
- Attempt 1: wait 1s
- Attempt 2: wait 2s
- Attempt 3: wait 4s (3 retries = 4 total attempts)

HTTP errors that are not retried: 403 Forbidden, 429 Too Many Requests. These indicate intentional blocking and raise `ScraperError` immediately.

### User-facing error format

Errors shown to the user (via `click.echo(..., err=True)`) follow this pattern:
```
Error: <what failed>
<actionable next step>
(<original exception if useful>)
```

---

## Extensibility points

### Multi-language support

Three places need changes:
1. `scraper.py`: The archive URL (`/study/general-conference`) and library key (`/eng/general-conference`) contain `eng`. A `--language` flag would need to parameterize these.
2. `epub_builder.py`: The `xml:lang` and `lang` attributes on the `<html>` element are hardcoded to `"en"`. These need to reflect the actual language.
3. `epub_builder.py`: The OPF `<dc:language>` element is hardcoded to `"en"`.

Encoding is already multi-language resilient -- the 4-priority encoding detection in `scraper._decode_response()` handles non-ASCII charsets.

### Batch mode (multiple conferences)

`cli.py` calls `_run()` once. A `--batch` flag could loop `_run()` over a list of conferences. The output directory structure already supports this: each conference gets its own subdirectory under `--output`.

### Alternative audio sources

`downloader.download_conference()` reads `talk.mp3_url` from the `Talk` objects. If the Church changes their CDN, only `scraper.parse_talk_page()` needs to update the URL extraction logic. The downloader, audio pipeline, and epub builder are all URL-agnostic.

### Adding new output formats

The pipeline passes a `Conference` object to both `build_m4b()` and `build_epub()`. A new output format (e.g., a plain text transcript dump, an RSS feed, or an MP3 playlist) would be a new function that accepts a `Conference` and an output path, called from `cli._run()` with a corresponding `--format-only` flag.

---

## Patterns that look wrong but are correct

These are code patterns a new contributor might flag as bugs or code smells. They are intentional. See [Technical Decisions, section 20](Technical-Decisions#20-design-patterns-that-look-suspicious-but-are-correct) for the full rationale behind each.

**Global cached paths in `ffmpeg_manager.py`:** Module-level globals cache the ffmpeg/ffprobe binary paths after first lookup. Looks like a code smell, but the lookup is expensive (PATH search + potential 80 MB download). `reset_cache()` exists for test isolation.

**Duplicate `sanitize_filename()` calls in `downloader.py` and `audio.py`:** Both modules independently sanitize the same talk title to construct the same filename. This is intentional decoupling -- sharing the computed name would couple the modules for negligible savings.

**Broad try/except in `audio.py._run()`:** Catches ffmpeg `-progress` flag failures and retries without it. Not a swallowed exception -- it is a deliberate fallback for older ffmpeg builds that do not support progress reporting.

**Per-thread `requests.Session` in `downloader.py`:** Each `ThreadPoolExecutor` worker creates its own session via `threading.local`. `requests.Session` is not thread-safe; sharing one would cause intermittent header/connection-pool corruption.

**`Progress.advance()` from worker threads:** Rich's `Progress` is documented as thread-safe. The cross-thread `advance()` calls in parallel image downloads are correct.

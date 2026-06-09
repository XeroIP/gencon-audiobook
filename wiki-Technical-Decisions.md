# Technical Decisions

This page documents every significant design decision in the project: what was chosen, what alternatives were considered, and why. This is the project's institutional memory.

---

## 1. Language: Python 3.10+

**Chosen:** Python 3.10+

**Alternatives considered:** Node.js/TypeScript, Go, Rust

**Rationale:**
Best library ecosystem for the problem:
- `requests` + `beautifulsoup4` for HTTP and HTML parsing
- `mutagen` for MP4/m4b metadata verification
- `Pillow` for image conversion and resizing
- `click` for CLI argument parsing
- `rich` for progress bars and formatted terminal output
- `static-ffmpeg` for automatic ffmpeg bundling

Python also has the largest pool of potential open-source contributors and is cross-platform without requiring compilation. Go or Rust would produce faster binaries, but the bottleneck here is network I/O and ffmpeg subprocess calls -- not Python interpretation speed.

---

## 2. ffmpeg: auto-download via static-ffmpeg

**Chosen:** `static-ffmpeg` Python package, which downloads a platform-specific static ffmpeg binary on first use

**Alternatives considered:**
- Require users to install ffmpeg manually
- Bundle ffmpeg binaries directly in the release archives

**Rationale:**
Manual installation is the single biggest source of support issues in open source audio tools. PATH problems, wrong versions, missing codecs, and platform-specific install differences all cause real friction. `static-ffmpeg` eliminates this entirely -- the user types one `pip install` and ffmpeg is handled automatically.

Bundling ffmpeg in releases was rejected because it inflates package size by ~80 MB per platform and has LGPL licensing implications that complicate the project's MIT license.

The tool still checks the system PATH first. If ffmpeg is already installed, `static-ffmpeg` is never invoked. The auto-download is a fallback, not a replacement.

---

## 3. Distribution: PyPI

**Chosen:** `pip install gencon-audiobook`

**Alternatives considered:** Standalone binaries (PyInstaller), Docker, Homebrew formula

**Rationale:**
PyPI is the standard Python distribution mechanism. It provides:
- Easy updates: `pip install --upgrade gencon-audiobook`
- Works on all platforms where Python works
- No special infrastructure to maintain

Standalone binaries (PyInstaller, Nuitka) are attractive for non-Python users but are fragile to cross-compile, large (include the Python runtime), and require per-platform build infrastructure. Docker adds unnecessary complexity for a simple CLI tool with no server component. A Homebrew formula would be macOS-only.

---

## 4. Audio format: m4b with AAC-LC, source-matched quality, mono

**Chosen:** AAC-LC codec, source-matched bitrate and sample rate, mono channel, `.m4b` container

**Alternatives considered:** HE-AAC v2, fixed bitrate defaults, stereo

**Bitrate/sample-rate: match the source**
The tool probes the first downloaded MP3 with ffprobe and uses the detected bitrate and sample rate as the AAC encoding target. Older conferences provide 32k MP3s; recent ones provide 128k. Encoding at a fixed default would either upsize low-quality sources (wasting space with no quality gain) or downsample high-quality sources (losing quality unnecessarily). Use `--bitrate` and `--sample-rate` to override.

**Codec: AAC-LC (not HE-AAC)**
HE-AAC v2 produces smaller files but has spotty decoder support on older Android audiobook players. AAC-LC is universally decoded on every modern platform.

**Channels: mono (not stereo)**
Conference talks are spoken word recorded in mono. Converting to stereo doubles the file size for zero audible benefit.

**Container: .m4b (not .mp3 or .aac)**
`.m4b` is the standard audiobook container. It supports chapters, embedded cover art, and full metadata. Every major audiobook player (Apple Books, Smart AudioBook Player, Sirin, Bound, BookPlayer) understands it. A plain MP3 has no standard chapter format.

**Platform compatibility:** Apple Books (iOS/macOS), Smart AudioBook Player (Android), Sirin (Android), BookPlayer (iOS), Bound (iOS), iTunes/Apple Music (Windows/macOS). Note: Google Play Books does **not** support `.m4b`.

---

## 5. EPUB: EPUB 3 reflowable, manual ZIP assembly, no hardcoded styles

**Chosen:** EPUB 3.0, reflowable layout, built by assembling a ZIP archive directly, JPEG images only, zero hardcoded colors/fonts/sizes in CSS

**Alternatives considered:** EPUB 2, fixed layout, ebooklib, WebP images

**EPUB 3 over EPUB 2:** All modern readers support EPUB 3. It is the current W3C standard. EPUB 2 was last revised in 2010.

**Reflowable over fixed layout:** Fixed-layout EPUB renders as garbled text on many Android readers. Reflowable adapts to any screen size and font size.

**Manual ZIP assembly over ebooklib:** `ebooklib` abstracts away too much of the EPUB structure and has historically had issues with EPUB 3 compliance. Building the ZIP directly gives full control over file structure, metadata, and the `mimetype` entry (which must be first and uncompressed per the EPUB spec). The EPUB format is not complex enough to justify a library abstraction.

**JPEG only, no WebP:** WebP is not yet a required EPUB media type. Older readers ignore or fail on WebP images. All images are converted to JPEG before embedding.

**No hardcoded CSS styles:** The stylesheet contains zero `color`, `background-color`, or `font-family` declarations. All visual styling is deferred to the reader application. This ensures dark mode, sepia mode, custom fonts, large text, and accessibility modes all work automatically on every reader.

> **Known issue:** The stylesheet currently contains two `font-size` declarations using relative `em` units (`0.85em` on `aside`, `0.8em` on `.para-num`). While `em` units are relative and less harmful than `px`/`pt`, they still override reader font-size preferences and interfere with accessibility large-text modes on some e-ink readers. These should be removed; see the open GitHub issue tracking the fix.

**Kindle:** Amazon accepts EPUB natively via "Send to Kindle" and auto-converts to AZW3. MOBI is dead (Amazon stopped accepting it in 2022). A valid EPUB 3 produces a clean Kindle conversion.

---

## 6. Scraping: requests + BeautifulSoup + html.parser

**Chosen:** `requests` for HTTP, `beautifulsoup4` with Python's built-in `html.parser` for parsing

**Alternatives considered:** Selenium/Playwright (headless browser), Scrapy, lxml parser

**No headless browser:** The Church website serves HTML with embedded JSON application state (`window.__INITIAL_STATE__`). No JavaScript execution is required to extract conference listings, talk metadata, audio URLs, or transcripts. A headless browser would add ~400 MB of dependencies and 10x the runtime for zero benefit.

**html.parser over lxml:** `html.parser` is part of the Python standard library -- no additional dependency. lxml is faster but requires a C extension, which complicates installation on some platforms. For this use case (parsing one HTML page at a time, not streaming gigabytes), the speed difference is immaterial.

**No Scrapy:** Scrapy is a framework designed for multi-site crawling at scale. This tool scrapes one site with a fixed structure. Using Scrapy would mean adopting a framework, learning its conventions, and accepting its abstractions for no benefit over plain requests.

**Dual-strategy parsing:** The scraper tries `__INITIAL_STATE__` JSON first (more stable, structured). If that fails (site redesign, A/B test, etc.), it falls back to HTML traversal using BeautifulSoup. This layered approach means a partial site change does not immediately break the tool.

---

## 7. Chapter metadata: "Title -- Speaker" format

**Chosen:** Chapter titles formatted as `"Talk Title -- Speaker Name"` (double ASCII hyphen)

**Alternatives considered:** Title only; separate metadata fields

**Rationale:**
The m4b chapter specification (FFMETADATA1) has no per-chapter "author" field -- only a title string. Embedding the speaker name in the chapter title is the only way to surface this information in audiobook players. Every major player (Apple Books, Smart AudioBook Player, Sirin) displays the chapter title prominently.

An em dash (`—`) would be more typographically correct, but FFMETADATA1 files are read by ffmpeg using the system codepage on Windows, which conflicts with the UTF-8 requirement of the MP4 container. ASCII-only chapter titles (using `--`) avoid this encoding conflict entirely.

---

## 8. Testing strategy

**Chosen:** Fixture-based unit tests + live smoke tests + weekly CI cron job

**Rationale:**

**Fixtures (`tests/fixtures/*.html`):** Saved HTML snapshots from the real website. Tests run against these snapshots so they are fast (no network), deterministic, and document exactly what the scraper expects. `scripts/update_fixtures.py` refreshes them when the site changes.

**Live smoke tests (`@pytest.mark.live`):** A small set of tests that hit the real website and verify that the scraper still works end-to-end. Excluded from normal CI (too slow, network-dependent). Run manually when making scraper changes.

**Weekly CI cron (`live-test.yml`):** GitHub Actions runs the live smoke tests every Monday. If they fail, a GitHub issue is automatically opened. This provides early warning when the Church updates their website structure between releases.

**Integration tests (`@pytest.mark.integration`):** Full pipeline test (scrape → download fixtures → build m4b → build epub) using programmatically generated silent MP3s. Requires ffmpeg on PATH. Excluded from normal CI.

---

## 9. Copyright handling

Downloaded content is copyright Intellectual Reserve, Inc. Tool code is MIT licensed. These are kept strictly separate.

- The m4b `comment` metadata field contains: "Copyright {year} Intellectual Reserve, Inc. All rights reserved. For personal, noncommercial use only."
- The EPUB includes a copyright page after the cover with the same notice and a disclaimer that the tool is unofficial and not affiliated with the Church.
- The README has a prominent disclaimer near the top.
- `LICENSE-CONTENT.md` in the repository explains the distinction between tool license and content license.
- Copyright year is derived from the conference year (not the current year).

---

## 10. Rate limiting: 0.5s delay between requests

**Chosen:** 500ms delay after each HTTP request

**Rationale:**
A full conference involves approximately:
- 1 archive page fetch
- 1 conference listing fetch
- ~33 individual talk page fetches
- ~33 MP3 downloads
- ~33 speaker photo downloads
- 1 cover image download

That is roughly 100 requests. Without any delay, these would fire as fast as the network allows -- potentially hitting the Church's servers with 100 rapid requests in a short window. That is rude, risks IP-based rate limiting, and is unnecessary. The 0.5s delay adds about 50 seconds to the total runtime, which is acceptable.

---

## 11. User-Agent transparency

**Chosen:** `gencon-audiobook/<version> (open source; github.com/XeroIP/gencon-audiobook)`

**Alternatives considered:** Impersonate a browser User-Agent string

**Rationale:**
Impersonating a browser to bypass bot detection is ethically problematic and unnecessary. The Church website does not require browser impersonation for publicly accessible content. Identifying as `gencon-audiobook` with a link to the GitHub repository allows the Church's infrastructure team to identify the tool, understand its purpose, and contact the project if needed.

---

## 12. Security decisions

**URL allowlisting:** Every URL is validated against an allowlist before any HTTP request is made. Only `churchofjesuschrist.org`, `*.churchofjesuschrist.org`, and `*.ldscdn.org` are permitted. This prevents the scraper from following unexpected redirects to third-party domains. Rejected URLs are logged at DEBUG level.

**Filename sanitization:** All file and directory names are derived from scraped content and sanitized to characters in `[a-zA-Z0-9 ._-]`. This prevents path traversal attacks, OS-specific filename issues, and null byte injection.

**No eval/exec:** The Church website embeds base64-encoded JSON in `window.__INITIAL_STATE__`. The scraper decodes the base64 and calls `json.loads()` only. The data is never executed.

**SSL always on:** `verify=False` is never used. If a certificate fails, it is a real problem worth surfacing, not something to bypass quietly.

**Explicit HTTP timeouts:** Every `requests` call has explicit connect and read timeouts (15s connect, 30s read for HTML; 30s connect, 120s read for MP3 downloads). There are no requests without timeouts.

**Encoding resilience:** HTTP responses are decoded using a 4-priority system: Content-Type header charset, HTML `<meta charset>` tag scanned from raw bytes, charset-normalizer statistical detection, UTF-8 fallback. Decoding uses `errors='replace'` so a single malformed byte never crashes the scraper.

---

## 13. Logging architecture

**Two destinations, always:**

1. **Console** (via `rich`): WARNING level by default. Only warnings, errors, and critical failures appear without `--verbose`. Add `--verbose` to see INFO and DEBUG-level detail including key milestones, URLs fetched, ffmpeg commands, file paths, and timing.

2. **Log file** (`<output_dir>/gencon-audiobook.log`): Always written at DEBUG level, regardless of `--verbose`. Full trace for troubleshooting. Created in the conference output directory so it stays with the data it describes.

**Log level conventions:**
- `DEBUG`: URLs fetched, CSS selectors matched, file paths, ffmpeg commands, timing
- `INFO`: Conference selected, downloading N talks, building audiobook/epub, output summary
- `WARNING`: Missing speaker photo, fallback selector used, retry attempt, single talk skipped
- `ERROR`: Single file failed after retries, single talk parse failed (recoverable, execution continues)
- `CRITICAL`: No valid talks found, ffmpeg unavailable, output directory not writable (unrecoverable)

**Common troubleshooting patterns:**
- "Could not find any talks" -- look for WARNING or ERROR about JSON selector and HTML fallback in the log
- "Download failed" -- look for HTTP status codes, timeout messages, and retry attempts
- "ffmpeg error" -- look for the exact ffmpeg command and the stderr output captured by the `_run()` helper
- A single bad talk -- look for ERROR lines mentioning the talk title; the rest of the conference continues

---

## 14. Conference metadata caching

**Chosen:** Serialize scraped `Conference` data to `conference.json` in the output directory after the first run. Subsequent runs load from this file, skipping ~38 HTTP requests per conference. Use `--force-scrape` to bypass.

**Rationale:**
Scraping a conference requires one archive page fetch, one listing page fetch, and one talk-page fetch per talk (~33+ requests). At 0.5s between requests, this is 15-20 seconds of network overhead even when nothing has changed. Caching eliminates this on every run after the first.

The cache file is stored in the conference output directory (next to the `.m4b` and `.epub`) rather than a global cache directory because it is tied to that specific conference's data. It is version-tagged so future format changes can invalidate old caches automatically. `--force-scrape` bypasses the cache when the user suspects stale data (e.g., after the Church corrects a transcript or MP3 URL).

**Format:** JSON, same structure as the `Conference` dataclass. Serialized by `cache.py` (`save_conference` / `load_conference`).

---

## 15. Parallel image downloads

**Chosen:** Cover image, speaker photos, and inline body images download concurrently using `ThreadPoolExecutor` with up to 8 worker threads. Each worker gets its own `requests.Session` via `threading.local`. MP3 audio downloads remain sequential.

**Alternatives considered:** Sequential download for all files; `asyncio`/`aiohttp`.

**Rationale:**
Images are small (typically 20-200 KB each) and numerous (~35+ per conference). Sequential downloading at 0.5s per image adds 15-20 seconds of latency-dominated wait time for no benefit. Parallelism eliminates this latency without stressing the server.

MP3 files are large (~3-5 MB each, 33+ files) and bandwidth-limited. Parallel MP3 downloads would compete for bandwidth without reducing wall-clock time, and would be impolite to the server. They remain sequential with a 0.5s courtesy delay.

`asyncio`/`aiohttp` was rejected because the rest of the pipeline is synchronous. Adding async to one phase would require propagating it up through `cli.py` or isolating it in a `asyncio.run()` call -- added complexity for no meaningful benefit over `ThreadPoolExecutor` for this workload.

`requests.Session` is not thread-safe. Each worker thread creates its own session on first use via `threading.local` storage (`_get_thread_session()`). The session is created once per thread and reused for all images that thread downloads.

---

## 16. EPUB 3 popup footnotes

**Chosen:** Footnote superscript links (`href="#noteN"`) are preserved through HTML sanitization with `epub:type="noteref"`. Footnote body elements are wrapped in `<aside epub:type="footnote">`. Modern EPUB 3 readers (Apple Books, Kobo, Thorium) display these as dismissible inline popovers; older readers fall back to an in-page anchor jump.

**Alternatives considered:** Strip all footnote links and render footnote text inline; ignore footnote structure entirely.

**Rationale:**
Conference talks occasionally include footnotes with scripture references. Stripping footnote links entirely loses this information. Rendering footnote text inline bloats the transcript and breaks the reading flow. EPUB 3's `epub:type="noteref"` / `epub:type="footnote"` semantics provide the ideal experience: the footnote is accessible without interrupting reading, and e-readers with popup support (most modern readers) handle it automatically.

The sanitizer's default behavior unwraps all `<a>` tags to remove external URLs. Footnote links are the deliberate exception: links with `class="note-ref"` and a `data-scroll-id="noteN"` attribute are preserved and normalised to a bare `href="#noteN"`, then annotated with `epub:type="noteref"`. The `data-scroll-id` attribute is used as the canonical note ID because the Church site generates full talk-page URLs (e.g. `/study/general-conference/2024/04/31bowen?lang=eng#note1`) rather than bare fragment hrefs, making `data-scroll-id` the more reliable signal. Bare `href="#noteN"` links are also accepted for robustness.

---

## 17. Portrait cover image

**Chosen:** The landscape conference cover image from the Church website is centered on a 1200x1800 gray canvas, producing a proper 2:3 portrait cover for reader library grids.

**Alternatives considered:** Use the landscape image as-is; crop to square.

**Rationale:**
EPUB reader library grids (Apple Books, Kindle, Kobo) display covers in portrait orientation. A landscape cover is squeezed, letterboxed, or distorted. Centering on a gray canvas preserves the original image without cropping and fills the expected 2:3 frame.

1200x1800 px matches the resolution of the source cover (fetched at 800px wide via IIIF; the 2:3 canvas results in 1200x1800 at that width). The gray background (`#808080`) is visually neutral on both light and dark reader themes.

---

## 18. JPEG images stored uncompressed in EPUB ZIP

**Chosen:** All JPEG images (cover, speaker photos, inline images) are stored with `ZIP_STORED` (no compression) in the EPUB ZIP archive. Other files use the default `ZIP_DEFLATED`.

**Alternatives considered:** Compress all files uniformly with DEFLATE.

**Rationale:**
JPEG is already a compressed format. Applying DEFLATE compression to a JPEG produces negligible size reduction (typically < 1%) because JPEG entropy is close to the theoretical minimum. However, some older e-ink readers decompress the ZIP entry before passing it to their JPEG decoder and have bugs when the JPEG is DEFLATE-wrapped. Using `ZIP_STORED` for JPEGs avoids this entirely with no meaningful size penalty.

---

## 19. IIIF URL resolution upgrade

**Chosen:** Conference cover and speaker photo URLs from the Church website are IIIF image URLs at 250px thumbnail resolution. The tool rewrites these to request 800px wide images before downloading.

**Rationale:**
The Church website embeds IIIF URLs sized for thumbnails (`/full/250,/0/default.jpg`). These look acceptable on the website but appear soft and pixelated when displayed as a cover in a reader app or as a speaker portrait in the EPUB. The IIIF spec allows requesting any resolution by replacing the size segment. Requesting 800px wide images costs no extra latency (same CDN, same request count) and dramatically improves image sharpness in the output files.

---

## 20. Design patterns that look suspicious but are correct

Several patterns in the codebase look like bugs or code smells on first read. They are intentional. This section documents them so future contributors do not "fix" them.

### Global state in `ffmpeg_manager.py`

`ffmpeg_manager.py` uses module-level globals (`_ffmpeg_path`, `_ffprobe_path`) to cache the discovered binary paths. This looks like a textbook code smell, but it is justified: locating ffmpeg involves `shutil.which()` and potentially downloading a ~80 MB binary via `static-ffmpeg`. That should happen exactly once per process. The module exposes `reset_cache()` for tests that need to swap mock paths between runs.

A class-based or context-manager approach was considered but rejected as unnecessary ceremony for what amounts to a pair of cached file paths with a well-defined lifetime (the process).

### Double `sanitize_filename()` calls for the same talk

Both `downloader.py` and `audio.py` independently call `sanitize_filename(talk.title)` to construct the same filename (e.g., `001-talk-title.mp3`). This looks like a DRY violation. It is intentional: the alternative is passing the sanitized filename between modules, which couples them. Both modules independently compute the same deterministic result from the same input. The redundancy keeps the modules independent and is cheaper than the abstraction that would eliminate it.

### Broad `try/except` in `audio.py._run()`

The `_run()` helper wraps ffmpeg subprocess calls in a broad try/except that catches failure of the `-progress` flag and retries without it. This looks like a swallowed exception, but it is deliberate fallback behavior: some older ffmpeg builds do not support `-progress pipe:1`, and the non-streaming fallback produces the same output. The behavior is documented in a code comment at the call site.

### `requests.Session` not shared across threads

`downloader.py` creates a new `requests.Session` per thread via `threading.local` instead of sharing one session. This looks like it wastes connections, but `requests.Session` is not thread-safe. Sharing it across `ThreadPoolExecutor` workers would cause intermittent corruption of headers, cookies, or connection pools. The per-thread pattern is the documented correct approach.

### Rich progress bar `advance()` called from worker threads

`downloader.py` calls `overall_progress.advance()` from within `ThreadPoolExecutor` worker threads. This looks like a thread-safety violation, but Rich's `Progress` class is documented as thread-safe. The pattern is correct and intentional.

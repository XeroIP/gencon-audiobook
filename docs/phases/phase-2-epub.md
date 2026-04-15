# Phase 2: EPUB Companion

## Objective

Add epub generation to the working tool from Phase 1. When this phase is complete,
`gencon-audiobook` must produce both a valid m4b and a valid epub. The epub must render
correctly in default, dark, and sepia themes across multiple reader apps.

Refer to `docs/spec.md` for technical decisions. Follow `.claude/rules/epub-style.md` for all
CSS and EPUB structure requirements.

---

## Prerequisites

- Phase 1 complete: scraper, downloader, audio pipeline, and CLI all working
- `gencon-audiobook --audiobook-only` produces a correct m4b

---

## Step 1: `epub_builder.py`

### Public API

```python
def build_epub(
    conference: Conference,
    images_dir: Path,
    output_path: Path,
) -> None:
    """Build an EPUB 3 companion with full transcripts and speaker photos.

    Generates the EPUB as a ZIP file containing XHTML chapters, a theme-safe
    stylesheet, embedded JPEG images, and a nav.xhtml with TOC nested by session.

    Args:
        conference: Fully populated Conference with transcript_html on each Talk.
        images_dir: Directory containing cover.jpg and speakers/*.jpg
        output_path: Path for the output .epub file.

    Raises:
        EpubError: if EPUB generation fails.
    """
```

Define `EpubError(Exception)`.

### EPUB File Structure

The final ZIP must contain these files:

```
mimetype                                        # first file, uncompressed, no newline
META-INF/container.xml
content.opf
nav.xhtml
style.css
text/cover.xhtml
text/copyright.xhtml
text/session-001-Saturday-Morning-Session.xhtml # session divider pages
text/session-002-Saturday-Afternoon-Session.xhtml
...
text/talk-001-Opening-Remarks.xhtml             # one per talk
text/talk-002-Talk-Title.xhtml
...
images/cover.jpg                                # ZIP_STORED (already compressed)
images/spk-001-Speaker-Name.jpg                 # ZIP_STORED
...
```

### `mimetype`

```
application/epub+zip
```

Must be the FIRST file in the ZIP. Must be stored uncompressed (`zipfile.ZIP_STORED`).
Must NOT have a trailing newline.

### Image compression

All JPEG images (cover, speaker photos, inline images) must be stored with
`compress_type=zipfile.ZIP_STORED`. JPEGs are already compressed — deflating them wastes
CPU on every page load for negligible savings, and double-compression causes compatibility
issues on some older e-ink readers.

All other files (XHTML, CSS, OPF, XML) use the default `ZIP_DEFLATED`.

### `META-INF/container.xml`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
```

### `content.opf`

EPUB 3 package document. Must include:
- `<metadata>` with dc:title, dc:creator ("General Conference"), dc:date (year), dc:rights
  (Intellectual Reserve copyright notice), dc:identifier (unique ID)
- `<meta property="dcterms:modified">` set to the actual build timestamp
  (`datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`), not a static date
- `<manifest>` listing every file in the EPUB with correct media types
- `<spine>` listing reading order: cover, copyright, then interleaved session divider pages
  and talks (session page followed by all its talks, for each session)

### `nav.xhtml`

EPUB 3 navigation document. Must contain two `<nav>` elements:

**TOC nav** — nested by session, session headers link to their divider page:

```html
<nav epub:type="toc" id="toc">
  <h2>Table of Contents</h2>
  <ol>
    <li><a href="text/cover.xhtml">Conference Title</a></li>
    <li><a href="text/copyright.xhtml">Copyright</a></li>
    <li>
      <a href="text/session-001-Saturday-Morning-Session.xhtml">Saturday Morning Session</a>
      <ol>
        <li><a href="text/talk-001-Opening-Remarks.xhtml">Opening Remarks — President Henry B. Eyring</a></li>
        <li><a href="text/talk-002-Talk-Title.xhtml">Talk Title — Speaker Name</a></li>
      </ol>
    </li>
  </ol>
</nav>
```

**Landmarks nav** — required for Kindle and accessibility tools:

```html
<nav epub:type="landmarks" hidden="hidden">
  <h2>Landmarks</h2>
  <ol>
    <li><a epub:type="cover" href="text/cover.xhtml">Cover</a></li>
    <li><a epub:type="toc" href="#toc">Table of Contents</a></li>
    <li><a epub:type="bodymatter" href="text/copyright.xhtml">Start of Content</a></li>
  </ol>
</nav>
```

### `style.css`

Theme-safe stylesheet. See `.claude/rules/epub-style.md` for the complete rules.

Allowed structural declarations only:
```css
body {
    margin: 1em 5%;
    line-height: 1.5;
    text-align: left;
}

h1 {
    font-size: 1.4em;
    margin: 1em 0 0.5em 0;
    font-weight: bold;
}

h2 {
    font-size: 1.2em;
    margin: 0.8em 0 0.3em 0;
    font-weight: bold;
}

p {
    margin: 0.5em 0;
}

.byline {
    font-style: italic;
    margin-bottom: 1em;
}

.speaker-photo {
    max-width: 40%;
    height: auto;
    display: block;
    margin: 0 auto 1em auto;
}

.transcript img {
    max-width: 100%;
    height: auto;
    display: block;
    margin: 1em auto;
}
```

**Verify before committing**: The stylesheet must contain zero occurrences of:
- `color:` or `color :`
- `background`
- `font-family`
- any numeric value followed by `px` or `pt`

### `text/cover.xhtml`

```xhtml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
  <title>Cover</title>
  <link rel="stylesheet" type="text/css" href="../style.css"/>
</head>
<body epub:type="cover">
  <img src="../images/cover.jpg" alt="Conference cover" style="max-width: 100%; height: auto;"/>
</body>
</html>
```

### `text/copyright.xhtml`

First page after cover. Must include:
- Conference title
- "Copyright [Year] Intellectual Reserve, Inc. All rights reserved."
- "This content is used for personal, noncommercial use in accordance with the Terms of Use
  of The Church of Jesus Christ of Latter-day Saints."
- "This is an unofficial tool not affiliated with The Church of Jesus Christ of Latter-day Saints."

### Session divider pages

One lightweight XHTML page per session, e.g. `text/session-001-Saturday-Morning-Session.xhtml`.
Contains only the session name as an `<h1>`. These give TOC session headers a unique
destination so they don't share a target with the first talk in the session.

```xhtml
<body>
  <h1>Saturday Morning Session</h1>
</body>
```

### Talk XHTML files

One file per talk, named `text/talk-NNN-{sanitized-title}.xhtml`.

Structure:
```xhtml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
  <title>{talk.title} — {talk.speaker}</title>
  <link rel="stylesheet" type="text/css" href="../style.css"/>
</head>
<body epub:type="chapter">
  <img class="speaker-photo" src="../images/spk-{talk.talk_index:03d}-{safe_speaker}.jpg" alt="{talk.speaker}"/>
  <p class="byline">{talk.speaker}</p>
  <h1>{talk.title}</h1>
  <div class="transcript">
    {sanitized_transcript_html}
  </div>
</body>
</html>
```

If no speaker photo is available, omit the `<img>` element entirely.

### Transcript HTML sanitization

Before embedding transcript HTML from the scraper:
- Strip all `<script>` and `<style>` elements and their content
- Materialize `data-value` attributes into text content before stripping — the Church site
  uses `<sup data-value="1"></sup>` (no text content) with CSS `content: attr(data-value)`
  to render footnote numbers; after stripping `data-*`, the number would vanish without this step
- Strip all `data-*` attributes (React/JS rendering artifacts)
- Strip all `class` attributes (Church site CSS classes have no EPUB stylesheet rules)
- Strip random web IDs (e.g. `id="p_fvoG6"`); preserve IDs beginning with `"note"` (footnote anchors)
- Unwrap all `<a>` tags — external links (scripture refs, footnote links) don't resolve in EPUB;
  keep display text and child elements (e.g. `<sup>`), remove the wrapper
- Remove `src` attributes pointing to external URLs; replace with local embedded image path
  where available, or remove the element if not
- Remove `javascript:` and `data:` URI schemes
- Ensure all tags are properly closed (XHTML requires this — use `_void_to_xhtml()` to
  self-close void elements like `<br>`, `<img>`, `<hr>`)
- All HTML entities must be valid XML entities

### Images

- **Cover image**: compose a portrait cover using `_make_portrait_cover()` — the Church's
  `og:image` is a 16:9 landscape banner; compose it onto a 1200x1800 gray canvas (2:3 portrait)
  so it displays correctly in reader library grids. Write as `images/cover.jpg` with `ZIP_STORED`.
- **Speaker photos**: locate each talk's photo at
  `images_dir/speakers/{talk.talk_index:03d}-{sanitize_filename(talk.speaker)}.jpg`.
  Resize to max 300px wide (maintaining aspect ratio) before embedding. Source photos are
  fetched at 800px via IIIF URL upgrade in the scraper — resize at embed time, not download time.
  Write with `ZIP_STORED`.
- If a speaker photo file does not exist for a talk, omit the `<img>` element in that chapter.
- All images must be JPEG.

### Post-write ZIP verification

After the `with zipfile.ZipFile(...)` block closes, call `testzip()` on the output file.
Raise `EpubError` if any entry is corrupt or the file is not a valid ZIP. This catches
truncated writes or filesystem-level damage early.

---

## Step 2: Update `cli.py` for `--epub-only`

Add the `--epub-only` flag (declared in Phase 1 but not wired up).

When `--epub-only`:
- Skip the ffmpeg check and audio conversion
- Still scrape (transcripts are needed) and download images (speaker photos needed for epub)
- Build epub only

Add `skip_audio: bool = False` parameter to `download_conference()` in `downloader.py`.
When `True`, skip all MP3 downloads and only download cover and speaker photos.
This keeps the downloader API clean rather than duplicating it.

In Phase 1 the `--epub-only` flag prints "epub generation coming in Phase 2" — wire it up here.

---

## Step 3: `test_epub.py`

```python
# All tests use a synthetic Conference with 2 sessions, 3 talks each (6 total)
# Synthetic speaker photos: 1x1 pixel JPEG blobs
# Synthetic cover: 1x1 pixel JPEG blob
```

Required tests:
- `test_build_epub_produces_valid_zip` — output is a valid ZIP file
- `test_build_epub_zip_passes_testzip` — `testzip()` returns None (no corrupt entries)
- `test_build_epub_mimetype_is_first_and_uncompressed` — mimetype is first entry, stored uncompressed
- `test_build_epub_contains_required_files` — container.xml, content.opf, nav.xhtml, style.css
- `test_build_epub_chapter_count` — talk files match total talk count
- `test_build_epub_has_session_divider_pages` — one session page per session
- `test_build_epub_toc_nested_by_session` — nav.xhtml contains session groupings with nested talk entries
- `test_nav_session_headers_link_to_divider_pages` — session TOC links point to session pages, not talks
- `test_nav_has_landmarks` — nav.xhtml has `epub:type="landmarks"` with cover, toc, bodymatter entries
- `test_cover_page_has_epub_type_cover` — cover.xhtml body has `epub:type="cover"`
- `test_talk_page_has_epub_type_chapter` — talk XHTML bodies have `epub:type="chapter"`
- `test_build_epub_spine_includes_session_pages` — OPF spine includes session divider pages
- `test_build_epub_all_talks_present` — every talk's title appears in a chapter XHTML file
- `test_build_epub_images_embedded` — images/cover.jpg and speaker images exist in ZIP
- `test_build_epub_images_are_jpeg` — all embedded images are JPEG (check magic bytes)
- `test_build_epub_images_stored_not_deflated` — all `images/*` entries use `ZIP_STORED`
- `test_build_epub_no_external_urls` — no `src` or `href` pointing to http(s):// URLs in content files
- `test_build_epub_css_no_color_declarations` — style.css contains no `color:` or `background`
- `test_build_epub_css_no_font_family` — style.css contains no `font-family`
- `test_build_epub_css_no_absolute_sizes` — style.css contains no `px` or `pt` text sizes
- `test_build_epub_css_has_transcript_img_rule` — style.css has `.transcript img` rule with `max-width`
- `test_build_epub_copyright_page_present` — copyright.xhtml exists and mentions Intellectual Reserve
- `test_build_epub_missing_speaker_photo_skips_img` — talk with no photo produces chapter without `<img>`
- `test_build_epub_opf_modified_is_recent` — `dcterms:modified` reflects actual build time (within 60s)
- `test_sanitize_transcript_materializes_data_value_for_empty_markers` — `<sup data-value="1"></sup>` becomes `<sup>1</sup>`
- `test_sanitize_transcript_preserves_existing_text_over_data_value` — existing text not overwritten by data-value
- `test_sanitize_transcript_strips_class_attributes` — all `class=` attributes removed
- `test_make_portrait_cover_produces_portrait_dimensions` — output height > width
- `test_make_portrait_cover_output_is_jpeg` — output starts with JPEG magic bytes
- `test_make_portrait_cover_uses_expected_dimensions` — output is 1200x1800

---

## Step 4: `test_integration.py`

End-to-end test marked `@pytest.mark.integration`. Uses mocked HTTP (no live requests).

```python
@pytest.mark.integration
def test_full_pipeline_produces_m4b_and_epub(tmp_path, mock_conference_responses):
    """Scrape -> download -> build m4b + epub from mocked HTTP responses."""
```

`mock_conference_responses` fixture provides:
- Conference archive HTML returning 3 fake conferences
- Conference listing HTML with 2 sessions and 4 talks
- Talk page HTML with MP3 URL, transcript, and speaker image URL
- MP3 responses: minimal valid MP3 bytes
- Image responses: minimal valid JPEG bytes

Assertions:
- m4b file exists and is non-zero size
- epub file exists and is non-zero size
- epub passes basic ZIP structure check (can be opened with zipfile)
- m4b chapter count matches talk count (via mutagen)

---

## Phase 2 Test Plan

```bash
# 1. Unit tests
pytest tests/test_epub.py -v

# 2. Integration test
pytest tests/test_integration.py -v -m integration

# 3. End-to-end: both outputs
gencon-audiobook --output ./test_output
# Expected: produces both .m4b and .epub

# 4. epub-only mode
gencon-audiobook --epub-only --output ./test_output2
# Expected: produces only .epub (no m4b, no ffmpeg invocation)

# 5. epubcheck validation (requires Java)
java -jar epubcheck.jar "test_output/<conference name>/<conference name>.epub"
# Expected: 0 errors (warnings acceptable)

# 6. Open epub on multiple platforms and verify:
#    a. Apple Books (macOS/iOS): cover displays as portrait, TOC shows sessions with nested talks,
#       session TOC entries link to session divider pages (not directly to first talk),
#       chapters open to correct talk, speaker photo visible, transcript readable,
#       footnote numbers visible inline
#    b. Google Play Books (Android): same checks
#    c. Calibre (desktop): landmarks nav visible in TOC panel, same content checks
#    d. Send to Kindle: verify clean conversion and TOC works

# 7. Theme compatibility — test on at least 2 reader apps:
#    a. Default/light theme: text readable, images display
#    b. Dark mode: text readable (not invisible), no white boxes around images
#    c. Sepia/warm theme: text adapts to theme colors
#    d. Change reader font: epub text uses the reader's chosen font
#    e. Increase text size: layout intact, no clipping or overflow

# 8. Coverage
pytest --cov=gencon_audiobook --cov-report=term-missing \
       --ignore=tests/test_scraper_live.py \
       --ignore=tests/test_integration.py
```

**Exit criteria**: All unit and integration tests pass. epub renders correctly in at least 2
different reader apps across default and dark themes. epubcheck reports 0 errors.

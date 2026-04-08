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

The final ZIP must contain these files in this order:

```
mimetype                          # first file, uncompressed, no newline
META-INF/container.xml
OEBPS/content.opf
OEBPS/nav.xhtml
OEBPS/stylesheet.css
OEBPS/cover.xhtml
OEBPS/copyright.xhtml
OEBPS/chapter-001-001.xhtml       # session 1, talk 1
OEBPS/chapter-001-002.xhtml       # session 1, talk 2
...
OEBPS/images/cover.jpg
OEBPS/images/speaker-001.jpg
...
```

### `mimetype`

```
application/epub+zip
```

Must be the FIRST file in the ZIP. Must be stored uncompressed (`zipfile.ZIP_STORED`).
Must NOT have a trailing newline.

### `META-INF/container.xml`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
```

### `OEBPS/content.opf`

EPUB 3 package document. Must include:
- `<metadata>` with dc:title, dc:creator ("General Conference"), dc:date (year), dc:rights
  (Intellectual Reserve copyright notice), dc:identifier (unique ID)
- `<manifest>` listing every file in the EPUB with correct media types
- `<spine>` listing reading order: cover, copyright, then chapters in order

### `OEBPS/nav.xhtml`

EPUB 3 navigation document. The TOC must be **nested by session**:

```html
<nav epub:type="toc" id="toc">
  <h1>Table of Contents</h1>
  <ol>
    <li>
      <span>Saturday Morning Session</span>
      <ol>
        <li><a href="chapter-001-001.xhtml">Opening Remarks -- President Henry B. Eyring</a></li>
        <li><a href="chapter-001-002.xhtml">Talk Title -- Speaker Name</a></li>
      </ol>
    </li>
    <li>
      <span>Saturday Afternoon Session</span>
      <ol>
        ...
      </ol>
    </li>
  </ol>
</nav>
```

Session entries use `<span>` (not `<a>`) since they have no content of their own.

### `OEBPS/stylesheet.css`

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

.session-divider {
    margin: 2em 0 1em 0;
    font-size: 1.1em;
    font-weight: bold;
}
```

**Verify before committing**: The stylesheet must contain zero occurrences of:
- `color:` or `color :`
- `background`
- `font-family`
- any numeric value followed by `px` or `pt`

### `OEBPS/cover.xhtml`

```xhtml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
  <title>Cover</title>
  <link rel="stylesheet" type="text/css" href="stylesheet.css"/>
</head>
<body epub:type="cover">
  <img src="images/cover.jpg" alt="Conference cover" style="max-width: 100%; height: auto;"/>
</body>
</html>
```

### `OEBPS/copyright.xhtml`

First page after cover. Must include:
- Conference title
- "Copyright [Year] Intellectual Reserve, Inc. All rights reserved."
- "This content is used for personal, noncommercial use in accordance with the Terms of Use
  of The Church of Jesus Christ of Latter-day Saints."
- "This is an unofficial tool not affiliated with The Church of Jesus Christ of Latter-day Saints."

### Chapter XHTML files

One file per talk, named `chapter-SSS-TTT.xhtml` (zero-padded session and talk numbers).

Structure:
```xhtml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
  <title>{talk.title}</title>
  <link rel="stylesheet" type="text/css" href="stylesheet.css"/>
</head>
<body>
  <img class="speaker-photo" src="images/speaker-{talk.talk_index:03d}.jpg" alt="{talk.speaker}"/>
  <p class="byline">{talk.speaker}</p>
  <h1>{talk.title}</h1>
  {sanitized_transcript_html}
</body>
</html>
```

If no speaker photo is available, omit the `<img>` element entirely.

### Transcript HTML sanitization

Before embedding transcript HTML from the scraper:
- Strip all `<script>` and `<style>` elements and their content
- Remove `src` attributes pointing to external URLs (images from the Church site are already
  downloaded — replace `src` with the local embedded image path, or remove if not available)
- Remove `href` attributes pointing to external URLs from `<a>` tags (keep the text, remove the link)
- Remove `onclick`, `onload`, and other event handlers
- Ensure all tags are properly closed (XHTML requires this)
- All HTML entities must be valid XML entities

### Images

- Copy `cover.jpg` from `images_dir` to `OEBPS/images/cover.jpg`
- Locate each talk's speaker photo using the same filename formula as `downloader.py`:
  `images_dir/speakers/{talk.talk_index:03d}-{sanitize_filename(talk.speaker)}.jpg`
  Copy to `OEBPS/images/speaker-{talk.talk_index:03d}.jpg`
- If a speaker photo file does not exist for a talk, omit the `<img>` element in that chapter
- All images must be JPEG — convert if necessary using Pillow
- Speaker photos: resize to max 300px wide (maintaining aspect ratio) before embedding
- If cover.jpg does not exist: skip the cover page image, use a text-only cover page

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
- `test_build_epub_mimetype_is_first_and_uncompressed` — mimetype is first entry, stored uncompressed
- `test_build_epub_contains_required_files` — container.xml, content.opf, nav.xhtml, stylesheet.css
- `test_build_epub_chapter_count` — chapter files match total talk count
- `test_build_epub_toc_nested_by_session` — nav.xhtml contains session groupings with nested talk entries
- `test_build_epub_all_talks_present` — every talk's title appears in a chapter XHTML file
- `test_build_epub_images_embedded` — images/cover.jpg and speaker images exist in ZIP
- `test_build_epub_images_are_jpeg` — all embedded images are JPEG (check magic bytes)
- `test_build_epub_no_external_urls` — no `src` or `href` pointing to http(s):// URLs in content files
- `test_build_epub_css_no_color_declarations` — stylesheet.css contains no `color:` or `background`
- `test_build_epub_css_no_font_family` — stylesheet.css contains no `font-family`
- `test_build_epub_css_no_absolute_sizes` — stylesheet.css contains no `px` or `pt` text sizes
- `test_build_epub_copyright_page_present` — copyright.xhtml exists and mentions Intellectual Reserve
- `test_build_epub_missing_speaker_photo_skips_img` — talk with no photo produces chapter without `<img>`

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
#    a. Apple Books (macOS/iOS): cover, TOC shows sessions with nested talks, chapters
#       open to correct talk, speaker photo visible, transcript readable
#    b. Google Play Books (Android): same checks
#    c. Calibre (desktop): same checks
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

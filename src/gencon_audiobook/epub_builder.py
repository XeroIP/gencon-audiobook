"""Generate an EPUB 3 companion with transcripts and speaker photos."""

from __future__ import annotations

import io
import logging
import re
import zipfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from bs4 import BeautifulSoup
from PIL import Image

from .models import Conference
from .utils import sanitize_filename

logger = logging.getLogger(__name__)

_COPYRIGHT = (
    "Copyright {year} Intellectual Reserve, Inc. "
    "All rights reserved. For personal, noncommercial use only."
)

_MAX_PHOTO_WIDTH = 300   # px — speaker photos (per epub-style.md)
_MAX_INLINE_WIDTH = 600  # px — inline body images (larger, they're content not thumbnails)
_JPEG_QUALITY = 85       # JPEG quality for all embedded images
_COVER_WIDTH = 1200      # px — portrait cover canvas width
_COVER_HEIGHT = 1800     # px — portrait cover canvas height (2:3 ratio)

# Void elements that must be self-closed in XHTML
_VOID_RE = re.compile(
    r"<(area|base|br|col|embed|hr|img|input|link|meta|param|source|track|wbr)"
    r"(\s[^>]*)?>",
    re.IGNORECASE,
)

_STYLESHEET = """\
/* gencon-audiobook EPUB stylesheet
   Zero color, background-color, font-family, or absolute font-size declarations.
   Full reader theme support (dark mode, sepia, custom fonts, accessibility). */

body {
  margin: 1em;
  line-height: 1.5;
}

h1, h2, h3 {
  text-align: center;
  margin: 1em 0 0.5em;
}

.cover {
  text-align: center;
  margin: 0;
  padding: 0;
}

.cover img {
  max-width: 100%;
  height: auto;
}

.cover-title {
  text-align: center;
  margin: 2em 0;
}

.copyright {
  margin: 2em 1em;
  text-align: center;
}

.copyright p {
  margin: 0.5em 0;
}

.speaker-photo {
  text-align: center;
  margin: 1em 0;
}

.speaker-photo img {
  max-width: 100%;
  width: 18em;
  height: auto;
}

.speaker-byline {
  text-align: center;
  font-style: italic;
  margin: 0.25em 0 0.5em;
}

.talk-title {
  text-align: center;
  margin: 0.5em 0 1em;
}

.transcript {
  margin: 1em 0;
}

.transcript p {
  margin: 0.5em 0;
  text-align: justify;
}

.transcript img {
  max-width: 100%;
  height: auto;
  display: block;
  margin: 1em auto;
}

nav ol {
  margin: 0;
  padding-left: 1.5em;
}

nav li {
  margin: 0.25em 0;
}

aside {
  margin: 1.5em 0 0.5em;
  padding-left: 1em;
}

.transcript.numbered {
  margin-left: 2.5em;
}

.para-num {
  float: left;
  width: 2em;
  margin-left: -2.5em;
  text-align: right;
  line-height: inherit;
}
"""


class EpubError(Exception):
    """Raised when EPUB assembly fails."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _void_to_xhtml(html: str) -> str:
    """Self-close HTML void elements so the result is valid XML.

    Args:
        html: HTML fragment, possibly with unclosed void elements.

    Returns:
        Same content with void elements self-closed (e.g., <br> -> <br/>).
    """
    def _close(m: re.Match) -> str:
        tag = m.group(1)
        attrs = m.group(2) or ""
        if attrs.rstrip().endswith("/"):
            return str(m.group(0))  # already self-closed
        return f"<{tag}{attrs}/>"
    return _VOID_RE.sub(_close, html)


def _sanitize_transcript(
    raw_html: str | None,
    inline_image_map: dict[str, str] | None = None,
    paragraph_numbers: bool = False,
) -> str:
    """Strip unsafe elements and external URLs from transcript HTML for EPUB embedding.

    Removes: <script>, <style>, <iframe>. External href/src attributes are removed
    to prevent broken external references in the EPUB container. All <a> link
    wrappers are unwrapped (display text and child elements are preserved inline)
    because scripture/footnote links point to the Church website and cannot
    resolve inside the EPUB container. data-* attributes and random web IDs are
    stripped to reduce file size. Inline images whose original URL is in
    inline_image_map have their src rewritten to the local EPUB path; remaining
    img attributes (srcset, sizes, loading, class) are stripped to just src and
    alt. Void elements are converted to XHTML self-closing form.

    If paragraph_numbers is True, each top-level transcript paragraph receives
    id="pN" and a prepended <span class="para-num">N</span> for left-margin
    numbering. Paragraphs inside <aside> (footnote bodies) are excluded.

    Args:
        raw_html: Raw HTML fragment from a scraped talk page, or None.
        inline_image_map: Optional mapping of original image URL -> EPUB-relative
            path (e.g., "../images/inline-001-assetid.jpg"). Images whose URL
            matches a key are kept with the local src; others are removed.
        paragraph_numbers: If True, prepend paragraph numbers to each <p> in the
            transcript and add id="pN" attributes.

    Returns:
        Sanitized XHTML fragment string, or empty string if input is None/empty.
    """
    if not raw_html:
        return ""

    soup = BeautifulSoup(raw_html, "html.parser")

    for tag in soup.find_all(["script", "style", "iframe"]):
        tag.decompose()

    # Rewrite inline image src before external-URL stripping removes them.
    # Strip all img attributes except src (rewritten) and alt.
    if inline_image_map:
        for img in soup.find_all("img"):
            # Resolve src/srcset to find a matching key in inline_image_map
            original_src = str(img.get("src") or "")
            srcset_raw = str(img.get("srcset") or "")
            local_path: str | None = inline_image_map.get(original_src)
            if not local_path and srcset_raw:
                for part in srcset_raw.split(","):
                    cand = part.strip().split()[0] if part.strip() else ""
                    if cand in inline_image_map:
                        local_path = inline_image_map[cand]
                        break
            alt = str(img.get("alt") or "")
            # Replace all attributes with just src+alt (or remove if not mapped)
            img.attrs.clear()
            if local_path:
                img["src"] = local_path
                img["alt"] = alt
            # If no local_path, img has no src — will be removed by the external-URL
            # stripping pass below (or left as empty <img/> which is harmless)
    else:
        # No map: just strip web-only img attributes, keep src/alt
        for img in soup.find_all("img"):
            src = str(img.get("src") or "")
            alt = str(img.get("alt") or "")
            img.attrs.clear()
            if src:
                img["src"] = src
            img["alt"] = alt

    for tag in soup.find_all(True):
        for attr in ("href", "src", "action", "formaction", "data"):
            val = tag.attrs.get(attr)
            if isinstance(val, str) and (
                val.startswith("http://")
                or val.startswith("https://")
                or val.startswith("//")
                or val.startswith("javascript:")
                or val.startswith("data:")  # data: URIs can embed arbitrary active content
            ):
                del tag.attrs[attr]

    # Preserve internal footnote links as EPUB 3 noterefs; unwrap everything else.
    # The Church site generates note-ref links with class="note-ref" and a full talk-page
    # URL ending in "#noteN" (e.g. href="/study/general-conference/2024/04/31bowen?lang=eng#note1").
    # These must be normalized to bare fragment refs ("#noteN") and marked epub:type="noteref"
    # so e-readers (Apple Books, Kobo, Thorium) can display the footnote as a dismissible popup.
    # Bare "#noteN" hrefs (from synthetic or pre-normalized content) are also accepted.
    # All other <a> tags (scripture refs, cross-refs) point outside the EPUB container
    # (RSC-033, RSC-026) and must be unwrapped.
    _NOTE_FRAGMENT_RE = re.compile(r"#(note\d+)$")
    for a_tag in soup.find_all("a"):
        href = str(a_tag.get("href") or "")
        scroll_id = str(a_tag.get("data-scroll-id") or "")
        note_id: str | None = None
        if scroll_id and re.match(r"^note\d+$", scroll_id):
            # Canonical case: Church note-ref link with data-scroll-id="noteN"
            note_id = scroll_id
        elif href.startswith("#note") and re.match(r"^#note\d+$", href):
            # Pre-normalized bare fragment ref
            note_id = href[1:]
        else:
            # Check for full URL ending in #noteN fragment
            m = _NOTE_FRAGMENT_RE.search(href)
            if m and "note-ref" in (a_tag.get("class") or []):
                note_id = m.group(1)
        if note_id:
            a_tag.attrs = {"href": f"#{note_id}", "epub:type": "noteref"}
        else:
            a_tag.unwrap()

    # Wrap footnote body elements in <aside epub:type="footnote">.
    # The Church site uses id="note1", id="note2", etc. on <li> elements inside
    # footer.notes for the footnote content. Moving the id to the wrapping <aside>
    # satisfies EPUB 3 structure: the noteref href="#note1" links to the aside, which
    # the reader renders as a popup.
    # Only match ids of exactly the form "note" + digits (e.g. "note1", "note12").
    # Do NOT match "note_title1" (section headings) or "note1_p1" (child elements).
    _FOOTNOTE_ID_RE = re.compile(r"^note\d+$")
    for tag in soup.find_all(
        lambda t: isinstance(t.get("id"), str) and bool(_FOOTNOTE_ID_RE.match(t["id"]))
    ):
        note_id = str(tag["id"])
        del tag["id"]
        aside = soup.new_tag("aside")
        aside["epub:type"] = "footnote"
        aside["id"] = note_id
        tag.wrap(aside)

    # Materialize data-value into text for elements that rely on CSS
    # content: attr(data-value) for display (e.g., footnote markers on the
    # Church site use <sup data-value="1"></sup> with no text content).
    for tag in soup.find_all(attrs={"data-value": True}):
        if not tag.get_text(strip=True):
            tag.string = str(tag["data-value"])

    # Strip data-* attributes (React/JS rendering artifacts), random web IDs
    # (e.g., id="p_fvoG6"), and web CSS class names that have no corresponding
    # rules in the EPUB stylesheet. Preserve only footnote anchor ids of the
    # form "noteN" (e.g., "note1") on <aside> elements. <img> class attrs are
    # already cleared above.
    _FOOTNOTE_ASIDE_ID_RE = re.compile(r"^note\d+$")
    for tag in soup.find_all(True):
        data_attrs = [attr for attr in tag.attrs if attr.startswith("data-")]
        for attr in data_attrs:
            del tag[attr]
        tag_id = tag.get("id")
        if isinstance(tag_id, str) and not _FOOTNOTE_ASIDE_ID_RE.match(tag_id):
            del tag["id"]
        if "class" in tag.attrs:
            del tag["class"]

    if paragraph_numbers:
        # Number each <p> that is not inside a footnote <aside>.
        # Prepend <span class="para-num">N</span> and add id="pN" for deep-linking.
        # Numbers restart at 1 per call (i.e., per talk).
        num = 0
        for p_tag in soup.find_all("p"):
            if p_tag.find_parent("aside"):
                continue  # footnote content — do not number
            num += 1
            p_tag["id"] = f"p{num}"
            span = soup.new_tag("span")
            span["class"] = "para-num"
            span.string = str(num)
            p_tag.insert(0, span)

    return _void_to_xhtml(str(soup))


def _resize_image(src_path: Path, max_width: int) -> bytes:
    """Load an image and resize to at most max_width pixels wide.

    Args:
        src_path: Path to the source image (any Pillow-supported format).
        max_width: Maximum output width in pixels.

    Returns:
        JPEG bytes of the (possibly resized) image.
    """
    with Image.open(src_path) as raw:
        # PIL stubs type resize()/convert() as Image.Image, not ImageFile.
        # Use a typed local variable to avoid mypy's ImageFile/Image mismatch.
        img: Image.Image = raw
        if img.width > max_width:
            ratio = max_width / img.width
            new_size = (max_width, int(img.height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def _resize_photo(src_path: Path) -> bytes:
    """Load a speaker photo and resize to at most _MAX_PHOTO_WIDTH pixels wide."""
    return _resize_image(src_path, _MAX_PHOTO_WIDTH)


def _make_portrait_cover(src_path: Path) -> bytes:
    """Compose a portrait EPUB cover from a landscape source image.

    The Church website provides a landscape banner (16:9) as the conference
    cover image. EPUB covers should be portrait to display correctly in
    reader library grids. This function places the landscape image centered
    on a neutral gray 2:3 portrait canvas.

    Args:
        src_path: Path to the source landscape JPEG.

    Returns:
        JPEG bytes of the portrait cover (_COVER_WIDTH x _COVER_HEIGHT).
    """
    with Image.open(src_path) as raw:
        src: Image.Image = raw.convert("RGB") if raw.mode != "RGB" else raw

        # Scale source image to fit within canvas width with 50px margin each side
        max_src_w = _COVER_WIDTH - 100
        if src.width > max_src_w:
            scale = max_src_w / src.width
            new_w = max_src_w
            new_h = int(src.height * scale)
        else:
            new_w, new_h = src.width, src.height
        src_scaled: Image.Image = src.resize((new_w, new_h), Image.Resampling.LANCZOS)

        canvas = Image.new("RGB", (_COVER_WIDTH, _COVER_HEIGHT), color=(128, 128, 128))
        # Center horizontally; position in the upper-middle of the canvas
        x = (_COVER_WIDTH - new_w) // 2
        y = (_COVER_HEIGHT - new_h) // 2
        canvas.paste(src_scaled, (x, y))

        buf = io.BytesIO()
        canvas.save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def _xhtml_wrap(
    title: str,
    body: str,
    css_href: str,
    body_epub_type: str | None = None,
) -> str:
    """Wrap body content in a complete XHTML5 document.

    Args:
        title: Document title for the <title> element.
        body: XHTML body content (must be valid XML).
        css_href: Relative path to the stylesheet from this document's location.
        body_epub_type: Optional epub:type value for the <body> element
            (e.g., "cover", "chapter"). Omitted when None.

    Returns:
        Complete XHTML5 document as a string.
    """
    body_attrs = f' epub:type="{body_epub_type}"' if body_epub_type else ""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"'
        ' xmlns:epub="http://www.idpf.org/2007/ops"'
        ' xml:lang="en" lang="en">\n'
        '<head>\n'
        '  <meta charset="utf-8"/>\n'
        f'  <title>{escape(title)}</title>\n'
        f'  <link rel="stylesheet" type="text/css" href="{css_href}"/>\n'
        '</head>\n'
        f'<body{body_attrs}>\n'
        f'{body}\n'
        '</body>\n'
        '</html>\n'
    )


def _cover_page(conference_title: str, has_cover_image: bool) -> str:
    """Generate the cover XHTML page.

    This file lives at text/cover.xhtml, so images are at ../images/.

    Args:
        conference_title: Conference title string.
        has_cover_image: True if cover.jpg is present in the images directory.

    Returns:
        Complete XHTML document string.
    """
    if has_cover_image:
        body = (
            '<div class="cover">\n'
            f'  <img src="../images/cover.jpg" alt="{escape(conference_title)}"/>\n'
            '</div>'
        )
    else:
        body = f'<h1 class="cover-title">{escape(conference_title)}</h1>'
    return _xhtml_wrap(conference_title, body, css_href="../style.css", body_epub_type="cover")


def _copyright_page(conference_title: str, year: int) -> str:
    """Generate the copyright XHTML page.

    Args:
        conference_title: Conference title string.
        year: Conference year, used in the Intellectual Reserve copyright notice.

    Returns:
        Complete XHTML document string.
    """
    notice = _COPYRIGHT.format(year=year)
    body = (
        '<div class="copyright">\n'
        f'  <p>{escape(conference_title)}</p>\n'
        f'  <p>{escape(notice)}</p>\n'
        '  <p>This EPUB file was created using an unofficial tool that is not affiliated with or endorsed by '
        'The Church of Jesus Christ of Latter-day Saints.</p>\n'
        '</div>'
    )
    return _xhtml_wrap("Copyright", body, css_href="../style.css")


def _session_page(session_name: str) -> str:
    """Generate a lightweight session divider XHTML page.

    Session dividers give TOC session headers a dedicated destination page,
    avoiding duplicate TOC targets where both the session header and the first
    talk entry would otherwise link to the same XHTML file.

    Args:
        session_name: Display name for the session (e.g., "Saturday Morning Session").

    Returns:
        Complete XHTML document string.
    """
    body = f'<h1>{escape(session_name)}</h1>'
    return _xhtml_wrap(session_name, body, css_href="../style.css")


def _talk_page(
    talk_title: str,
    speaker: str,
    transcript_html: str | None,
    photo_href: str | None,
    inline_image_map: dict[str, str] | None = None,
    paragraph_numbers: bool = False,
) -> str:
    """Generate a talk XHTML page with speaker photo, byline, title, and transcript.

    Args:
        talk_title: Title of the talk.
        speaker: Speaker's name.
        transcript_html: Raw transcript HTML fragment, or None.
        photo_href: Relative path to speaker photo from this page's location, or None.
        inline_image_map: Optional mapping of original image URL -> EPUB-relative path.
        paragraph_numbers: If True, add left-margin paragraph numbers to transcript.

    Returns:
        Complete XHTML document string.
    """
    parts: list[str] = []

    if photo_href:
        parts.append(
            '<div class="speaker-photo">\n'
            f'  <img src="{photo_href}" alt="{escape(speaker)}"/>\n'
            '</div>'
        )

    parts.append(
        f'<p class="speaker-byline">{escape(speaker)}</p>\n'
        f'<h1 class="talk-title">{escape(talk_title)}</h1>'
    )

    sanitized = _sanitize_transcript(
        transcript_html,
        inline_image_map=inline_image_map,
        paragraph_numbers=paragraph_numbers,
    )
    transcript_class = "transcript numbered" if paragraph_numbers else "transcript"
    if sanitized:
        parts.append(f'<div class="{transcript_class}">\n{sanitized}\n</div>')
    else:
        parts.append(f'<div class="{transcript_class}"><p>[Transcript not available.]</p></div>')

    body = "\n".join(parts)
    return _xhtml_wrap(
        f"{talk_title} \u2014 {speaker}",
        body,
        css_href="../style.css",
        body_epub_type="chapter",
    )


def _nav_xhtml(
    conference: Conference,
    talk_hrefs: dict[int, str],
    session_hrefs: dict[int, str] | None = None,
) -> str:
    """Generate the EPUB 3 navigation document with a nested session/talk TOC.

    nav.xhtml lives at the EPUB root, so talk hrefs use text/filename.xhtml.

    Args:
        conference: Conference with sessions and talks populated.
        talk_hrefs: Mapping from talk_index to href relative to nav.xhtml.
        session_hrefs: Optional mapping from session.number to href for session
            divider pages. When provided, session headers link to their divider
            page instead of the first talk, avoiding duplicate TOC targets.

    Returns:
        Complete nav.xhtml XHTML document string.
    """
    toc: list[str] = [
        '<nav epub:type="toc" id="toc">',
        '  <h2>Table of Contents</h2>',
        '  <ol>',
        f'    <li><a href="text/cover.xhtml">{escape(conference.title)}</a></li>',
        '    <li><a href="text/copyright.xhtml">Copyright</a></li>',
    ]
    for session in conference.sessions:
        toc.append('    <li>')
        if session_hrefs and session.number in session_hrefs:
            # Link to dedicated session divider page
            toc.append(f'      <a href="{session_hrefs[session.number]}">{escape(session.name)}</a>')
        elif session.talks:
            # Fallback: link to first talk in session
            first_href = talk_hrefs[session.talks[0].talk_index]
            toc.append(f'      <a href="{first_href}">{escape(session.name)}</a>')
        else:
            toc.append(f'      <span>{escape(session.name)}</span>')
        toc.append('      <ol>')
        for talk in session.talks:
            href = talk_hrefs[talk.talk_index]
            toc.append(f'        <li><a href="{href}">{escape(talk.title)}</a></li>')
        toc.append('      </ol>')
        toc.append('    </li>')
    toc += ['  </ol>', '</nav>']

    # Landmarks nav: tells reading systems where the cover, TOC, and body
    # matter begin. The hidden attribute prevents visual rendering while
    # keeping the structure machine-readable for accessibility tools.
    first_talk_href = ""
    for session in conference.sessions:
        if session.talks:
            first_talk_href = talk_hrefs[session.talks[0].talk_index]
            break
    landmarks = [
        '<nav epub:type="landmarks" hidden="hidden">',
        '  <h2>Landmarks</h2>',
        '  <ol>',
        '    <li><a epub:type="cover" href="text/cover.xhtml">Cover</a></li>',
        '    <li><a epub:type="toc" href="#toc">Table of Contents</a></li>',
        f'    <li><a epub:type="bodymatter" href="{first_talk_href or "text/copyright.xhtml"}">'
        'Start of Content</a></li>',
        '  </ol>',
        '</nav>',
    ]

    body = "\n".join(toc) + "\n" + "\n".join(landmarks)

    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"'
        ' xmlns:epub="http://www.idpf.org/2007/ops"'
        ' xml:lang="en" lang="en">\n'
        '<head>\n'
        '  <meta charset="utf-8"/>\n'
        f'  <title>{escape(conference.title)} \u2014 Table of Contents</title>\n'
        '  <link rel="stylesheet" type="text/css" href="style.css"/>\n'
        '</head>\n'
        '<body>\n'
        f'{body}\n'
        '</body>\n'
        '</html>\n'
    )


def _content_opf(
    conference: Conference,
    talk_items: list[tuple[str, str]],
    image_items: list[tuple[str, str]],
    has_cover: bool,
    spine_items: list[tuple[str, str]] | None = None,
) -> str:
    """Generate the OPF package document.

    Args:
        conference: Conference metadata for title, date, and rights fields.
        talk_items: List of (manifest-id, href) for all content XHTML files (manifest).
        image_items: List of (manifest-id, href) for image files.
        has_cover: Whether cover.jpg is present.
        spine_items: Optional ordered list of (manifest-id, href) for the spine. When
            provided, this controls reading order (e.g., session dividers before talks).
            When None, talk_items is used for the spine.

    Returns:
        OPF XML document as a string.
    """
    uid = f"gencon-audiobook-{conference.year}-{conference.month:02d}"
    rights = escape(_COPYRIGHT.format(year=conference.year))
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines: list[str] = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">',
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">',
        f'    <dc:identifier id="uid">{uid}</dc:identifier>',
        f'    <dc:title>{escape(conference.title)}</dc:title>',
        '    <dc:creator>The Church of Jesus Christ of Latter-day Saints</dc:creator>',
        f'    <dc:date>{conference.year}-{conference.month:02d}-01</dc:date>',
        '    <dc:language>en</dc:language>',
        f'    <dc:rights>{rights}</dc:rights>',
        f'    <meta property="dcterms:modified">{modified}</meta>',
    ]
    if has_cover:
        lines.append('    <meta name="cover" content="img-cover"/>')
    lines += [
        '  </metadata>',
        '  <manifest>',
        '    <item id="nav" href="nav.xhtml"'
        ' media-type="application/xhtml+xml" properties="nav"/>',
        '    <item id="style" href="style.css" media-type="text/css"/>',
        '    <item id="page-cover" href="text/cover.xhtml"'
        ' media-type="application/xhtml+xml"/>',
        '    <item id="page-copyright" href="text/copyright.xhtml"'
        ' media-type="application/xhtml+xml"/>',
    ]
    for item_id, href in talk_items:
        lines.append(
            f'    <item id="{item_id}" href="{href}" media-type="application/xhtml+xml"/>'
        )
    if has_cover:
        lines.append(
            '    <item id="img-cover" href="images/cover.jpg"'
            ' media-type="image/jpeg" properties="cover-image"/>'
        )
    for item_id, href in image_items:
        lines.append(f'    <item id="{item_id}" href="{href}" media-type="image/jpeg"/>')
    lines += [
        '  </manifest>',
        '  <spine>',
        # nav.xhtml must be in the spine for landmarks href="#toc" to satisfy RSC-011.
        # linear="no" keeps it out of the normal reading flow.
        '    <itemref idref="nav" linear="no"/>',
        '    <itemref idref="page-cover"/>',
        '    <itemref idref="page-copyright"/>',
    ]
    for item_id, _ in (spine_items if spine_items is not None else talk_items):
        lines.append(f'    <itemref idref="{item_id}"/>')
    lines += ['  </spine>', '</package>']
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_epub(
    conference: Conference,
    images_dir: Path,
    output_path: Path,
    paragraph_numbers: bool = False,
) -> None:
    """Build an EPUB 3 companion with full transcripts and speaker photos.

    EPUB ZIP structure:
      mimetype                        (uncompressed, must be first)
      META-INF/container.xml
      content.opf
      nav.xhtml
      style.css
      text/cover.xhtml
      text/copyright.xhtml
      text/talk-NNN-title.xhtml          (one per talk)
      images/cover.jpg                   (if present in images_dir)
      images/spk-NNN-speaker.jpg         (one per talk that has a photo)
      images/inline-NNN-assetid.jpg      (one per inline body image)

    Speaker photos are resized to at most 300 px wide before embedding.
    Inline body images are resized to at most 600 px wide.

    Args:
        conference: Fully populated Conference. talk.transcript_html is used for body
            text; talks with no transcript get a placeholder.
        images_dir: Directory containing cover.jpg and speakers/*.jpg.
        output_path: Destination path for the .epub file. Parent is created if needed.
        paragraph_numbers: If True, prepend left-margin paragraph numbers to each
            transcript paragraph and add id="pN" attributes for deep-linking.

    Raises:
        EpubError: if the output file cannot be written.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    talks = conference.talks

    cover_src = images_dir / "cover.jpg"
    has_cover = cover_src.exists()

    # Compute per-talk filenames and image paths
    talk_file_data: list[dict] = []
    for talk in talks:
        safe_title = sanitize_filename(talk.title)
        filename = f"talk-{talk.talk_index:03d}-{safe_title}.xhtml"
        item_id = f"talk-{talk.talk_index:03d}"

        safe_speaker = sanitize_filename(talk.speaker)
        photo_src = images_dir / "speakers" / f"{talk.talk_index:03d}-{safe_speaker}.jpg"
        if photo_src.exists():
            # Path from text/ to images/
            photo_page_href = f"../images/spk-{talk.talk_index:03d}-{safe_speaker}.jpg"
            # Path from EPUB root
            photo_epub_href = f"images/spk-{talk.talk_index:03d}-{safe_speaker}.jpg"
        else:
            photo_page_href = None
            photo_epub_href = None

        # Build inline image map: original URL -> EPUB-relative path (from text/)
        inline_image_map: dict[str, str] = {}
        inline_image_files: list[tuple[str, Path, str]] = []  # (epub_href, src_path, manifest_id)
        for img in talk.inline_images:
            safe_id = sanitize_filename(img.asset_id)
            src_path = images_dir / "inline" / f"{talk.talk_index:03d}-{safe_id}.jpg"
            if src_path.exists():
                epub_href = f"images/inline-{talk.talk_index:03d}-{safe_id}.jpg"
                page_href = f"../images/inline-{talk.talk_index:03d}-{safe_id}.jpg"
                manifest_id = f"img-inline-{talk.talk_index:03d}-{safe_id}"
                inline_image_map[img.url] = page_href
                inline_image_files.append((epub_href, src_path, manifest_id))

        talk_file_data.append({
            "talk": talk,
            "filename": filename,
            "item_id": item_id,
            "photo_src": photo_src if photo_src.exists() else None,
            "photo_page_href": photo_page_href,
            "photo_epub_href": photo_epub_href,
            "inline_image_map": inline_image_map,
            "inline_image_files": inline_image_files,
        })

    talk_items = [(d["item_id"], f"text/{d['filename']}") for d in talk_file_data]
    image_items: list[tuple[str, str]] = [
        (f"img-{d['item_id']}", d["photo_epub_href"])
        for d in talk_file_data
        if d["photo_epub_href"]
    ]
    # Add inline images to manifest
    for d in talk_file_data:
        for epub_href, _src, manifest_id in d["inline_image_files"]:
            image_items.append((manifest_id, epub_href))
    # talk_hrefs: relative from nav.xhtml at EPUB root
    talk_hrefs: dict[int, str] = {
        d["talk"].talk_index: f"text/{d['filename']}" for d in talk_file_data
    }

    # Session divider pages: each session gets a lightweight page so TOC session
    # headers can link to a unique destination rather than the first talk.
    session_file_data: list[dict[str, str]] = []
    session_hrefs: dict[int, str] = {}
    for session in conference.sessions:
        safe_name = sanitize_filename(session.name)
        filename = f"session-{session.number:03d}-{safe_name}.xhtml"
        item_id = f"session-{session.number:03d}"
        href = f"text/{filename}"
        session_file_data.append({
            "session_name": session.name,
            "filename": filename,
            "item_id": item_id,
        })
        session_hrefs[session.number] = href

    # Build interleaved spine: session divider page followed by its talks,
    # for each session. This is the order content pages appear in the EPUB spine.
    spine_items: list[tuple[str, str]] = []
    talk_item_lookup: dict[int, tuple[str, str]] = {
        d["talk"].talk_index: (d["item_id"], f"text/{d['filename']}") for d in talk_file_data
    }
    session_item_lookup: dict[int, tuple[str, str]] = {
        session.number: (
            f"session-{session.number:03d}",
            f"text/session-{session.number:03d}-{sanitize_filename(session.name)}.xhtml",
        )
        for session in conference.sessions
    }
    for session in conference.sessions:
        spine_items.append(session_item_lookup[session.number])
        for talk in session.talks:
            spine_items.append(talk_item_lookup[talk.talk_index])

    # All XHTML content items for the manifest (order doesn't matter for manifest)
    all_xhtml_items = list(session_item_lookup.values()) + talk_items

    logger.info("Building EPUB: %s (%d talks)", output_path.name, len(talks))

    try:
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # mimetype must be first and stored uncompressed (EPUB spec requirement)
            mime_info = zipfile.ZipInfo("mimetype")
            mime_info.compress_type = zipfile.ZIP_STORED
            zf.writestr(mime_info, "application/epub+zip")

            zf.writestr(
                "META-INF/container.xml",
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<container version="1.0"'
                ' xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
                '  <rootfiles>\n'
                '    <rootfile full-path="content.opf"'
                ' media-type="application/oebps-package+xml"/>\n'
                '  </rootfiles>\n'
                '</container>\n',
            )

            zf.writestr("style.css", _STYLESHEET)
            zf.writestr(
                "content.opf",
                _content_opf(
                    conference,
                    all_xhtml_items,
                    image_items,
                    has_cover,
                    spine_items=spine_items,
                ),
            )
            zf.writestr("nav.xhtml", _nav_xhtml(conference, talk_hrefs, session_hrefs))
            zf.writestr("text/cover.xhtml", _cover_page(conference.title, has_cover))
            zf.writestr(
                "text/copyright.xhtml",
                _copyright_page(conference.title, conference.year),
            )

            for d in session_file_data:
                zf.writestr(f"text/{d['filename']}", _session_page(d["session_name"]))
                logger.debug("Added session page: text/%s", d["filename"])

            for d in talk_file_data:
                talk = d["talk"]
                page = _talk_page(
                    talk.title,
                    talk.speaker,
                    talk.transcript_html,
                    d["photo_page_href"],
                    inline_image_map=d["inline_image_map"] or None,
                    paragraph_numbers=paragraph_numbers,
                )
                zf.writestr(f"text/{d['filename']}", page)
                logger.debug("Added talk page: text/%s", d["filename"])

            if has_cover:
                # Compose a portrait cover from the landscape source image —
                # e-reader library grids expect portrait (2:3) covers.
                # JPEGs are already compressed — store to avoid double-compression.
                cover_bytes = _make_portrait_cover(cover_src)
                zf.writestr("images/cover.jpg", cover_bytes, compress_type=zipfile.ZIP_STORED)
                logger.debug("Added cover image (portrait composition)")

            for d in talk_file_data:
                if d["photo_src"] and d["photo_epub_href"]:
                    try:
                        photo_bytes = _resize_photo(d["photo_src"])
                        zf.writestr(d["photo_epub_href"], photo_bytes, compress_type=zipfile.ZIP_STORED)
                        logger.debug("Added speaker photo: %s", d["photo_epub_href"])
                    except (OSError, RuntimeError, ValueError) as exc:
                        logger.warning(
                            "Could not embed speaker photo for %r: %s — skipping",
                            d["talk"].speaker,
                            exc,
                        )

            for d in talk_file_data:
                for epub_href, src_path, _manifest_id in d["inline_image_files"]:
                    try:
                        img_bytes = _resize_image(src_path, _MAX_INLINE_WIDTH)
                        zf.writestr(epub_href, img_bytes, compress_type=zipfile.ZIP_STORED)
                        logger.debug("Added inline image: %s", epub_href)
                    except (OSError, RuntimeError, ValueError) as exc:
                        logger.warning(
                            "Could not embed inline image %s: %s — skipping",
                            src_path.name,
                            exc,
                        )

        # Verify ZIP integrity after close() — catches truncated writes or corrupt entries.
        try:
            bad = zipfile.ZipFile(output_path).testzip()
            if bad is not None:
                raise EpubError(f"EPUB ZIP verification failed: corrupt entry {bad!r}")
        except zipfile.BadZipFile as exc:
            raise EpubError(f"EPUB ZIP is not a valid ZIP file: {exc}") from exc

    except OSError as exc:
        raise EpubError(f"Failed to write EPUB to {output_path}: {exc}") from exc

    size_mb = output_path.stat().st_size / 1_048_576
    logger.info(
        "Built EPUB: %s (%.1f MB, %d talks)", output_path.name, size_mb, len(talks)
    )

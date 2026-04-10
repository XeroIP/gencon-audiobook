"""Generate an EPUB 3 companion with transcripts and speaker photos."""

from __future__ import annotations

import io
import logging
import re
import zipfile
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

_MAX_PHOTO_WIDTH = 300  # px — per epub-style.md
_JPEG_QUALITY = 85      # JPEG quality for all embedded images

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

nav ol {
  margin: 0;
  padding-left: 1.5em;
}

nav li {
  margin: 0.25em 0;
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


def _sanitize_transcript(raw_html: str | None) -> str:
    """Strip unsafe elements and external URLs from transcript HTML for EPUB embedding.

    Removes: <script>, <style>, <iframe>. External href/src attributes are removed
    to prevent broken external references in the EPUB container.
    Void elements are converted to XHTML self-closing form.

    Args:
        raw_html: Raw HTML fragment from a scraped talk page, or None.

    Returns:
        Sanitized XHTML fragment string, or empty string if input is None/empty.
    """
    if not raw_html:
        return ""

    soup = BeautifulSoup(raw_html, "html.parser")

    for tag in soup.find_all(["script", "style", "iframe"]):
        tag.decompose()

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

    return _void_to_xhtml(str(soup))


def _resize_photo(src_path: Path) -> bytes:
    """Load a speaker photo and resize to at most _MAX_PHOTO_WIDTH pixels wide.

    Args:
        src_path: Path to the source JPEG.

    Returns:
        JPEG bytes of the (possibly resized) image.
    """
    with Image.open(src_path) as raw:
        # PIL stubs type resize()/convert() as Image.Image, not ImageFile.
        # Use a typed local variable to avoid mypy's ImageFile/Image mismatch.
        img: Image.Image = raw
        if img.width > _MAX_PHOTO_WIDTH:
            ratio = _MAX_PHOTO_WIDTH / img.width
            new_size = (_MAX_PHOTO_WIDTH, int(img.height * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def _xhtml_wrap(title: str, body: str, css_href: str) -> str:
    """Wrap body content in a complete XHTML5 document.

    Args:
        title: Document title for the <title> element.
        body: XHTML body content (must be valid XML).
        css_href: Relative path to the stylesheet from this document's location.

    Returns:
        Complete XHTML5 document as a string.
    """
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
        '<body>\n'
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
    return _xhtml_wrap(conference_title, body, css_href="../style.css")


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


def _talk_page(
    talk_title: str,
    speaker: str,
    transcript_html: str | None,
    photo_href: str | None,
) -> str:
    """Generate a talk XHTML page with speaker photo, byline, title, and transcript.

    Args:
        talk_title: Title of the talk.
        speaker: Speaker's name.
        transcript_html: Raw transcript HTML fragment, or None.
        photo_href: Relative path to speaker photo from this page's location, or None.

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

    sanitized = _sanitize_transcript(transcript_html)
    if sanitized:
        parts.append(f'<div class="transcript">\n{sanitized}\n</div>')
    else:
        parts.append('<div class="transcript"><p>[Transcript not available.]</p></div>')

    body = "\n".join(parts)
    return _xhtml_wrap(f"{talk_title} \u2014 {speaker}", body, css_href="../style.css")


def _nav_xhtml(conference: Conference, talk_hrefs: dict[int, str]) -> str:
    """Generate the EPUB 3 navigation document with a nested session/talk TOC.

    nav.xhtml lives at the EPUB root, so talk hrefs use text/filename.xhtml.

    Args:
        conference: Conference with sessions and talks populated.
        talk_hrefs: Mapping from talk_index to href relative to nav.xhtml.

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
        toc.append(f'      <span>{escape(session.name)}</span>')
        toc.append('      <ol>')
        for talk in session.talks:
            href = talk_hrefs[talk.talk_index]
            toc.append(f'        <li><a href="{href}">{escape(talk.title)}</a></li>')
        toc.append('      </ol>')
        toc.append('    </li>')
    toc += ['  </ol>', '</nav>']
    body = "\n".join(toc)

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
) -> str:
    """Generate the OPF package document.

    Args:
        conference: Conference metadata for title, date, and rights fields.
        talk_items: List of (manifest-id, href) for talk XHTML files, in spine order.
        image_items: List of (manifest-id, href) for speaker photo images.
        has_cover: Whether cover.jpg is present.

    Returns:
        OPF XML document as a string.
    """
    uid = f"gencon-audiobook-{conference.year}-{conference.month:02d}"
    rights = escape(_COPYRIGHT.format(year=conference.year))
    modified = f"{conference.year}-{conference.month:02d}-01T00:00:00Z"

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
        '    <itemref idref="page-cover"/>',
        '    <itemref idref="page-copyright"/>',
    ]
    for item_id, _ in talk_items:
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
      text/talk-NNN-title.xhtml      (one per talk)
      images/cover.jpg               (if present in images_dir)
      images/spk-NNN-speaker.jpg     (one per talk that has a photo)

    Speaker photos are resized to at most 300 px wide before embedding.

    Args:
        conference: Fully populated Conference. talk.transcript_html is used for body
            text; talks with no transcript get a placeholder.
        images_dir: Directory containing cover.jpg and speakers/*.jpg.
        output_path: Destination path for the .epub file. Parent is created if needed.

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

        talk_file_data.append({
            "talk": talk,
            "filename": filename,
            "item_id": item_id,
            "photo_src": photo_src if photo_src.exists() else None,
            "photo_page_href": photo_page_href,
            "photo_epub_href": photo_epub_href,
        })

    talk_items = [(d["item_id"], f"text/{d['filename']}") for d in talk_file_data]
    image_items = [
        (f"img-{d['item_id']}", d["photo_epub_href"])
        for d in talk_file_data
        if d["photo_epub_href"]
    ]
    # talk_hrefs: relative from nav.xhtml at EPUB root
    talk_hrefs: dict[int, str] = {
        d["talk"].talk_index: f"text/{d['filename']}" for d in talk_file_data
    }

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
                _content_opf(conference, talk_items, image_items, has_cover),
            )
            zf.writestr("nav.xhtml", _nav_xhtml(conference, talk_hrefs))
            zf.writestr("text/cover.xhtml", _cover_page(conference.title, has_cover))
            zf.writestr(
                "text/copyright.xhtml",
                _copyright_page(conference.title, conference.year),
            )

            for d in talk_file_data:
                talk = d["talk"]
                page = _talk_page(
                    talk.title,
                    talk.speaker,
                    talk.transcript_html,
                    d["photo_page_href"],
                )
                zf.writestr(f"text/{d['filename']}", page)
                logger.debug("Added talk page: text/%s", d["filename"])

            if has_cover:
                zf.write(cover_src, "images/cover.jpg")
                logger.debug("Added cover image")

            for d in talk_file_data:
                if d["photo_src"] and d["photo_epub_href"]:
                    try:
                        photo_bytes = _resize_photo(d["photo_src"])
                        zf.writestr(d["photo_epub_href"], photo_bytes)
                        logger.debug("Added speaker photo: %s", d["photo_epub_href"])
                    except Exception as exc:
                        logger.warning(
                            "Could not embed speaker photo for %r: %s — skipping",
                            d["talk"].speaker,
                            exc,
                        )

    except OSError as exc:
        raise EpubError(f"Failed to write EPUB to {output_path}: {exc}") from exc

    size_mb = output_path.stat().st_size / 1_048_576
    logger.info(
        "Built EPUB: %s (%.1f MB, %d talks)", output_path.name, size_mb, len(talks)
    )

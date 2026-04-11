"""Tests for epub_builder.py — EPUB structure and content validation."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from conftest import make_jpeg as _make_jpeg
from gencon_audiobook.epub_builder import (
    EpubError,
    _make_portrait_cover,
    _sanitize_transcript,
    _void_to_xhtml,
    build_epub,
)
from gencon_audiobook.models import Conference, Session, Talk


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------



def _make_conference(n_talks: int = 3, include_transcripts: bool = True) -> Conference:
    """Build a Conference with n_talks distributed across two sessions."""
    talks: list[Talk] = []
    for i in range(1, n_talks + 1):
        transcript = f"<p>Transcript paragraph {i}.</p>" if include_transcripts else None
        talks.append(
            Talk(
                title=f"Talk {i}",
                speaker=f"Speaker {i}",
                talk_url=f"https://www.churchofjesuschrist.org/t{i}",
                talk_index=i,
                transcript_html=transcript,
            )
        )

    mid = max(1, n_talks // 2)
    sessions = [
        Session(name="Morning Session", number=1, talks=talks[:mid]),
        Session(name="Afternoon Session", number=2, talks=talks[mid:]),
    ]
    return Conference(
        title="April 2024 General Conference",
        year=2024,
        month=4,
        cover_image_url=None,
        sessions=sessions,
        conference_url="https://www.churchofjesuschrist.org/study/general-conference/2024/04",
    )


def _epub_names(epub_path: Path) -> set[str]:
    """Return the set of all file names inside the EPUB ZIP."""
    with zipfile.ZipFile(epub_path) as zf:
        return set(zf.namelist())


def _epub_read(epub_path: Path, name: str) -> bytes:
    """Read a single file from the EPUB ZIP by name."""
    with zipfile.ZipFile(epub_path) as zf:
        return zf.read(name)


# ---------------------------------------------------------------------------
# _void_to_xhtml
# ---------------------------------------------------------------------------


def test_void_to_xhtml_closes_br() -> None:
    assert _void_to_xhtml("<br>") == "<br/>", "bare <br> should become <br/>"


def test_void_to_xhtml_closes_img() -> None:
    result = _void_to_xhtml('<img src="x.jpg" alt="test">')
    assert result == '<img src="x.jpg" alt="test"/>', f"Got {result!r}"


def test_void_to_xhtml_leaves_already_closed_alone() -> None:
    result = _void_to_xhtml("<br/>")
    assert result == "<br/>", "Already-closed void elements should not be double-closed"


def test_void_to_xhtml_leaves_non_void_open() -> None:
    result = _void_to_xhtml("<p>Hello</p>")
    assert result == "<p>Hello</p>", "Non-void elements should be unchanged"


# ---------------------------------------------------------------------------
# _sanitize_transcript
# ---------------------------------------------------------------------------


def test_sanitize_transcript_returns_empty_for_none() -> None:
    assert _sanitize_transcript(None) == "", "None input should return empty string"


def test_sanitize_transcript_returns_empty_for_empty_string() -> None:
    assert _sanitize_transcript("") == "", "Empty input should return empty string"


def test_sanitize_transcript_strips_script_tags() -> None:
    html = "<p>Text.</p><script>alert('xss')</script>"
    result = _sanitize_transcript(html)
    assert "<script>" not in result, "script tags must be removed"
    assert "alert" not in result, "script content must be removed"


def test_sanitize_transcript_strips_style_tags() -> None:
    html = "<p>Text.</p><style>body { color: red; }</style>"
    result = _sanitize_transcript(html)
    assert "<style>" not in result, "style tags must be removed"


def test_sanitize_transcript_strips_external_href() -> None:
    html = '<p><a href="https://evil.com/track">Link</a></p>'
    result = _sanitize_transcript(html)
    assert "https://evil.com" not in result, "external href must be removed"
    assert "Link" in result, "link text should be preserved"


def test_sanitize_transcript_strips_external_src() -> None:
    html = '<img src="https://tracker.example.com/pixel.gif"/>'
    result = _sanitize_transcript(html)
    assert "https://tracker.example.com" not in result, "external src must be removed"


def test_sanitize_transcript_preserves_paragraph_content() -> None:
    html = "<p>The word of God is a lamp.</p><p>Second paragraph.</p>"
    result = _sanitize_transcript(html)
    assert "lamp" in result, "paragraph text should be preserved"
    assert "Second paragraph" in result


def test_sanitize_transcript_self_closes_void_elements() -> None:
    html = "<p>Line one.<br>Line two.</p>"
    result = _sanitize_transcript(html)
    assert "<br>" not in result, "bare <br> must be self-closed in output"
    assert "<br/>" in result or "<br />" in result, f"Expected self-closed br, got: {result!r}"


def test_sanitize_transcript_strips_data_uri_href() -> None:
    """data: URIs in href attributes must be removed — they can embed active content."""
    html = '<p><a href="data:text/html,<script>alert(1)</script>">click</a></p>'
    result = _sanitize_transcript(html)
    assert "data:" not in result, (
        f"data: URI should be stripped from href, got: {result!r}"
    )
    assert "click" in result, "Link text should be preserved even when href is stripped"


def test_sanitize_transcript_strips_data_uri_src() -> None:
    """data: URIs in src attributes must also be removed."""
    html = '<p><img src="data:image/png;base64,abc123" alt="img"/></p>'
    result = _sanitize_transcript(html)
    assert "data:" not in result, (
        f"data: URI should be stripped from src, got: {result!r}"
    )


def test_sanitize_transcript_unwraps_scripture_ref_links() -> None:
    """Scripture reference links must be unwrapped — text preserved, <a> removed."""
    html = '<p><a class="scripture-ref" href="/study/scriptures/bofm/alma/5">Alma 5:12</a></p>'
    result = _sanitize_transcript(html)
    assert "<a" not in result, f"<a> tag must be removed, got: {result!r}"
    assert "Alma 5:12" in result, "Link text must be preserved"


def test_sanitize_transcript_unwraps_note_ref_links() -> None:
    """Footnote note-ref links must be unwrapped — superscript preserved, <a> removed."""
    html = '<p>See this.<a class="note-ref" href="#note1"><sup class="marker">1</sup></a></p>'
    result = _sanitize_transcript(html)
    assert "<a" not in result, f"<a> tag must be removed, got: {result!r}"
    assert "<sup" in result, "Superscript must be preserved after unwrapping"


def test_sanitize_transcript_strips_data_attributes() -> None:
    """data-* attributes must be stripped — they are web rendering artifacts."""
    html = '<p data-aid="abc123" data-type="verse">Content.</p>'
    result = _sanitize_transcript(html)
    assert "data-aid" not in result, f"data-aid must be stripped, got: {result!r}"
    assert "data-type" not in result, f"data-type must be stripped, got: {result!r}"
    assert "Content." in result, "Paragraph content must be preserved"


def test_sanitize_transcript_strips_random_ids() -> None:
    """Random web-generated id attributes must be stripped."""
    html = '<p id="p_fvoG6">Text.</p>'
    result = _sanitize_transcript(html)
    assert 'id="p_fvoG6"' not in result, f"Random id must be stripped, got: {result!r}"
    assert "Text." in result, "Paragraph content must be preserved"


def test_sanitize_transcript_preserves_note_ids() -> None:
    """id attributes starting with 'note' must be preserved for footnote anchors."""
    html = '<p id="note1">Footnote text.</p>'
    result = _sanitize_transcript(html)
    assert 'id="note1"' in result, f"note id must be preserved, got: {result!r}"


# ---------------------------------------------------------------------------
# build_epub — basic structure
# ---------------------------------------------------------------------------


def test_build_epub_creates_file(tmp_path: Path) -> None:
    conference = _make_conference(n_talks=2)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    assert output.exists(), "EPUB output file should be created"
    assert output.stat().st_size > 0, "EPUB output file should be non-empty"


def test_build_epub_contains_required_files(tmp_path: Path) -> None:
    conference = _make_conference(n_talks=2)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    names = _epub_names(output)
    for required in (
        "mimetype",
        "META-INF/container.xml",
        "content.opf",
        "nav.xhtml",
        "style.css",
        "text/cover.xhtml",
        "text/copyright.xhtml",
    ):
        assert required in names, f"Required file missing from EPUB: {required!r}"


def test_build_epub_mimetype_is_uncompressed(tmp_path: Path) -> None:
    """The mimetype entry must be stored uncompressed (EPUB 3 spec requirement)."""
    conference = _make_conference(n_talks=2)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    with zipfile.ZipFile(output) as zf:
        info = zf.getinfo("mimetype")
        assert info.compress_type == zipfile.ZIP_STORED, (
            f"mimetype must be ZIP_STORED, got compress_type={info.compress_type}"
        )


def test_build_epub_mimetype_value(tmp_path: Path) -> None:
    conference = _make_conference(n_talks=2)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    content = _epub_read(output, "mimetype").decode("ascii")
    assert content == "application/epub+zip", f"Unexpected mimetype: {content!r}"


def test_build_epub_mimetype_is_first_entry(tmp_path: Path) -> None:
    """mimetype must be the first entry in the ZIP for EPUB spec compliance."""
    conference = _make_conference(n_talks=2)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    with zipfile.ZipFile(output) as zf:
        first = zf.namelist()[0]
    assert first == "mimetype", f"First ZIP entry must be 'mimetype', got {first!r}"


def test_build_epub_one_xhtml_per_talk(tmp_path: Path) -> None:
    n = 4
    conference = _make_conference(n_talks=n)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    names = _epub_names(output)
    talk_pages = [f for f in names if f.startswith("text/talk-")]
    assert len(talk_pages) == n, (
        f"Expected {n} talk XHTML files, got {len(talk_pages)}: {sorted(talk_pages)}"
    )


def test_build_epub_talk_titles_in_nav(tmp_path: Path) -> None:
    conference = _make_conference(n_talks=3)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    nav = _epub_read(output, "nav.xhtml").decode("utf-8")
    for talk in conference.talks:
        assert talk.title in nav, f"Talk title {talk.title!r} not found in nav.xhtml"


def test_build_epub_sessions_in_nav(tmp_path: Path) -> None:
    conference = _make_conference(n_talks=4)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    nav = _epub_read(output, "nav.xhtml").decode("utf-8")
    for session in conference.sessions:
        assert session.name in nav, (
            f"Session name {session.name!r} not found in nav.xhtml"
        )


def test_build_epub_session_headers_are_links(tmp_path: Path) -> None:
    """Session headers in nav.xhtml must use <a> not <span> for reader compatibility."""
    conference = _make_conference(n_talks=2)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    nav = _epub_read(output, "nav.xhtml").decode("utf-8")
    session_name = conference.sessions[0].name
    assert f"<span>{session_name}</span>" not in nav, \
        "Session header must not use <span>"
    assert f">{session_name}</a>" in nav, \
        "Session header must use <a> linking to first talk"


# ---------------------------------------------------------------------------
# build_epub — images
# ---------------------------------------------------------------------------


def test_build_epub_embeds_cover_image(tmp_path: Path) -> None:
    _make_jpeg(tmp_path / "cover.jpg")
    conference = _make_conference(n_talks=2)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    assert "images/cover.jpg" in _epub_names(output), \
        "cover.jpg should be embedded when present"


def test_build_epub_no_cover_image_still_builds(tmp_path: Path) -> None:
    """EPUB should build successfully even when cover.jpg is absent."""
    conference = _make_conference(n_talks=2)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    assert output.exists(), "EPUB should build without a cover image"
    assert "images/cover.jpg" not in _epub_names(output), \
        "cover.jpg should not be listed when absent"


def test_build_epub_embeds_speaker_photos(tmp_path: Path) -> None:
    conference = _make_conference(n_talks=2)
    # Create speaker photos matching the expected filenames
    for talk in conference.talks:
        from gencon_audiobook.utils import sanitize_filename
        name = sanitize_filename(talk.speaker)
        photo = tmp_path / "speakers" / f"{talk.talk_index:03d}-{name}.jpg"
        _make_jpeg(photo, size=(400, 500))  # wider than 300px to test resize

    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    names = _epub_names(output)
    speaker_images = [f for f in names if f.startswith("images/spk-")]
    assert len(speaker_images) == 2, (
        f"Expected 2 speaker images, got {len(speaker_images)}: {sorted(speaker_images)}"
    )


def test_build_epub_missing_speaker_photo_skipped_gracefully(tmp_path: Path) -> None:
    """EPUB should build even when speaker photos are absent."""
    conference = _make_conference(n_talks=3)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    # Should succeed without any speaker photos
    assert output.exists()
    names = _epub_names(output)
    assert not any(f.startswith("images/spk-") for f in names), \
        "No speaker images should be embedded when none were downloaded"


def test_build_epub_embeds_inline_images(tmp_path: Path) -> None:
    """Inline images with downloaded files are embedded and src rewritten."""
    from gencon_audiobook.models import InlineImage
    from gencon_audiobook.utils import sanitize_filename

    asset_id = "abc123xyz"
    original_url = f"https://www.churchofjesuschrist.org/imgs/{asset_id}/full/%21500%2C/0/default"

    talk = Talk(
        title="Talk With Image",
        speaker="Speaker One",
        talk_url="https://www.churchofjesuschrist.org/t1",
        talk_index=1,
        transcript_html=f'<p>Text.</p><img src="{original_url}" alt="A photo"/>',
        inline_images=[InlineImage(url=original_url, alt="A photo", asset_id=asset_id)],
    )
    session = Session(name="Morning Session", number=1, talks=[talk])
    conference = Conference(
        title="Test Conference",
        year=2024,
        month=4,
        cover_image_url=None,
        sessions=[session],
        conference_url="https://www.churchofjesuschrist.org/study/general-conference/2024/04",
    )

    # Write a fake inline image to the expected download location
    safe_id = sanitize_filename(asset_id)
    inline_dir = tmp_path / "inline"
    inline_dir.mkdir()
    _make_jpeg(inline_dir / f"001-{safe_id}.jpg")

    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)

    names = _epub_names(output)
    inline_images = [n for n in names if n.startswith("images/inline-")]
    assert len(inline_images) == 1, \
        f"Expected 1 inline image in EPUB, got {len(inline_images)}: {inline_images}"

    # Verify src rewritten in the talk XHTML
    filename = f"talk-001-{sanitize_filename(talk.title)}.xhtml"
    page = _epub_read(output, f"text/{filename}").decode("utf-8")
    assert original_url not in page, "Original external URL must not appear in talk XHTML"
    assert "inline-001-" in page, "Rewritten local inline image path must appear in talk XHTML"


def test_build_epub_missing_inline_image_skipped_gracefully(tmp_path: Path) -> None:
    """If the inline image file was not downloaded, EPUB still builds without it."""
    from gencon_audiobook.models import InlineImage

    asset_id = "missingasset"
    original_url = f"https://www.churchofjesuschrist.org/imgs/{asset_id}/full/%21500%2C/0/default"

    talk = Talk(
        title="Talk Missing Image",
        speaker="Speaker One",
        talk_url="https://www.churchofjesuschrist.org/t1",
        talk_index=1,
        transcript_html=f'<img src="{original_url}" alt="missing"/>',
        inline_images=[InlineImage(url=original_url, alt="missing", asset_id=asset_id)],
    )
    session = Session(name="Morning Session", number=1, talks=[talk])
    conference = Conference(
        title="Test Conference",
        year=2024,
        month=4,
        cover_image_url=None,
        sessions=[session],
        conference_url="https://www.churchofjesuschrist.org/study/general-conference/2024/04",
    )

    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)  # file not on disk, should not raise
    assert output.exists(), "EPUB should still build when inline image file is missing"
    names = _epub_names(output)
    assert not any(n.startswith("images/inline-") for n in names), \
        "No inline images should be embedded when files are not on disk"


# ---------------------------------------------------------------------------
# build_epub — content validation
# ---------------------------------------------------------------------------


def test_build_epub_copyright_notice_present(tmp_path: Path) -> None:
    conference = _make_conference(n_talks=2)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    copyright_page = _epub_read(output, "text/copyright.xhtml").decode("utf-8")
    assert "Intellectual Reserve" in copyright_page, \
        "Copyright page must contain Intellectual Reserve notice"
    assert "2024" in copyright_page, "Copyright page should include the conference year"


def test_build_epub_transcript_appears_in_talk_page(tmp_path: Path) -> None:
    conference = _make_conference(n_talks=2, include_transcripts=True)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    # Check first talk's page
    talk = conference.talks[0]
    from gencon_audiobook.utils import sanitize_filename
    filename = f"talk-{talk.talk_index:03d}-{sanitize_filename(talk.title)}.xhtml"
    page = _epub_read(output, f"text/{filename}").decode("utf-8")
    assert "Transcript paragraph 1" in page, \
        "Transcript content should appear in the talk XHTML page"


def test_build_epub_placeholder_when_no_transcript(tmp_path: Path) -> None:
    conference = _make_conference(n_talks=2, include_transcripts=False)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    talk = conference.talks[0]
    from gencon_audiobook.utils import sanitize_filename
    filename = f"talk-{talk.talk_index:03d}-{sanitize_filename(talk.title)}.xhtml"
    page = _epub_read(output, f"text/{filename}").decode("utf-8")
    assert "not available" in page.lower(), \
        "Placeholder message should appear when transcript is absent"


def test_build_epub_opf_lists_all_talk_items(tmp_path: Path) -> None:
    n = 3
    conference = _make_conference(n_talks=n)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    opf = _epub_read(output, "content.opf").decode("utf-8")
    for i in range(1, n + 1):
        item_id = f'id="talk-{i:03d}"'
        assert item_id in opf, f"OPF manifest should list {item_id!r}"


# ---------------------------------------------------------------------------
# build_epub — CSS compliance (epub-style.md)
# ---------------------------------------------------------------------------


def test_build_epub_css_has_no_color_declarations(tmp_path: Path) -> None:
    conference = _make_conference(n_talks=2)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    css = _epub_read(output, "style.css").decode("utf-8")
    css_no_comments = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    assert not re.search(r"\bcolor\s*:", css_no_comments), \
        "CSS must not contain color declarations (breaks reader themes)"


def test_build_epub_css_has_no_background_color(tmp_path: Path) -> None:
    conference = _make_conference(n_talks=2)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    css = _epub_read(output, "style.css").decode("utf-8")
    css_no_comments = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    assert not re.search(r"\bbackground(-color)?\s*:", css_no_comments), \
        "CSS must not contain background-color declarations"


def test_build_epub_css_has_no_font_family(tmp_path: Path) -> None:
    conference = _make_conference(n_talks=2)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    css = _epub_read(output, "style.css").decode("utf-8")
    css_no_comments = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    assert not re.search(r"\bfont-family\s*:", css_no_comments), \
        "CSS must not contain font-family declarations"


def test_build_epub_css_has_no_absolute_font_sizes(tmp_path: Path) -> None:
    conference = _make_conference(n_talks=2)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    css = _epub_read(output, "style.css").decode("utf-8")
    css_no_comments = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    # Absolute units: px, pt, cm, mm, in, pc
    assert not re.search(r"\bfont-size\s*:[^;]*\d(px|pt|cm|mm|in|pc)\b", css_no_comments), \
        "CSS must not use absolute font-size units (px, pt, cm, mm, in, pc)"


# ---------------------------------------------------------------------------
# build_epub — OPF correctness
# ---------------------------------------------------------------------------


def test_build_epub_opf_cover_meta_absent_when_no_cover(tmp_path: Path) -> None:
    """When cover.jpg is absent, the OPF must NOT emit <meta name="cover">.

    If the cover meta references a manifest item that doesn't exist, epubcheck
    will report an error and some readers will refuse to open the file.
    """
    conference = _make_conference(n_talks=2)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    opf = _epub_read(output, "content.opf").decode("utf-8")
    assert 'name="cover"' not in opf, \
        "OPF cover meta must be absent when cover.jpg is not present"


def test_build_epub_opf_cover_meta_present_when_cover_exists(tmp_path: Path) -> None:
    """When cover.jpg is present, the OPF must emit <meta name="cover">."""
    _make_jpeg(tmp_path / "cover.jpg")
    conference = _make_conference(n_talks=2)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    opf = _epub_read(output, "content.opf").decode("utf-8")
    assert 'name="cover"' in opf and 'content="img-cover"' in opf, \
        "OPF cover meta must be present and reference 'img-cover' when cover.jpg exists"


def test_build_epub_opf_spine_order_matches_talk_order(tmp_path: Path) -> None:
    """The OPF spine must list talks in the same order as conference.talks.

    An alphabetically or id-sorted spine would break reading order in strict
    EPUB readers that follow the spine rather than the TOC.
    """
    conference = _make_conference(n_talks=5)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    opf = _epub_read(output, "content.opf").decode("utf-8")
    spine_ids = re.findall(r'idref="(talk-\d+)"', opf)
    expected = [f"talk-{t.talk_index:03d}" for t in conference.talks]
    assert spine_ids == expected, (
        f"OPF spine order mismatch.\nExpected: {expected}\nGot:      {spine_ids}"
    )


# ---------------------------------------------------------------------------
# build_epub — image handling edge cases
# ---------------------------------------------------------------------------


def test_build_epub_speaker_photo_resized_to_max_width(tmp_path: Path) -> None:
    """Speaker photos wider than 300 px must be resized before embedding.

    Without this check, a regression in _resize_photo (e.g., changing
    _MAX_PHOTO_WIDTH) would silently embed full-size photos.
    """
    conference = _make_conference(n_talks=1)
    talk = conference.talks[0]
    from gencon_audiobook.utils import sanitize_filename
    name = sanitize_filename(talk.speaker)
    photo = tmp_path / "speakers" / f"{talk.talk_index:03d}-{name}.jpg"
    _make_jpeg(photo, size=(600, 800))  # intentionally wider than 300 px

    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)

    with zipfile.ZipFile(output) as zf:
        spk_name = next(n for n in zf.namelist() if n.startswith("images/spk-"))
        img_bytes = zf.read(spk_name)

    import io as _io
    img = Image.open(_io.BytesIO(img_bytes))
    assert img.width <= 300, \
        f"Embedded speaker photo should be <= 300 px wide, got {img.width} px"


def test_build_epub_corrupted_speaker_photo_skipped_gracefully(tmp_path: Path) -> None:
    """A corrupt speaker photo on disk must not abort the EPUB build.

    A partially-downloaded file that survived cleanup would trigger this.
    The EPUB should be produced without that photo rather than raising.
    """
    conference = _make_conference(n_talks=1)
    talk = conference.talks[0]
    from gencon_audiobook.utils import sanitize_filename
    name = sanitize_filename(talk.speaker)
    photo = tmp_path / "speakers" / f"{talk.talk_index:03d}-{name}.jpg"
    photo.parent.mkdir(parents=True, exist_ok=True)
    photo.write_bytes(b"this is not a jpeg at all")  # corrupt

    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)  # must not raise

    assert output.exists(), "EPUB should still be produced despite corrupt speaker photo"
    names = _epub_names(output)
    assert not any(n.startswith("images/spk-") for n in names), \
        "Corrupt photo must be silently skipped, not embedded"


# ---------------------------------------------------------------------------
# build_epub — content escaping
# ---------------------------------------------------------------------------


def test_build_epub_title_with_special_chars_escaped(tmp_path: Path) -> None:
    """Talk titles and speaker names containing HTML special characters must be escaped.

    A title like 'Faith & Works' must appear as 'Faith &amp; Works' in XHTML.
    Unescaped ampersands make the XHTML invalid XML and will fail epubcheck.
    """
    conference = _make_conference(n_talks=1)
    conference.talks[0].title = "Faith & Works"
    conference.talks[0].speaker = "Elder A. <Test>"

    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)

    from gencon_audiobook.utils import sanitize_filename
    # sanitize_filename strips < and > so we need to find the actual filename
    with zipfile.ZipFile(output) as zf:
        talk_page = next(n for n in zf.namelist() if n.startswith("text/talk-001-"))
        page = zf.read(talk_page).decode("utf-8")

    assert "&amp;" in page, "Ampersand in title must be HTML-escaped as &amp;"
    assert "<Elder" not in page, "Unescaped angle bracket in speaker name must not appear"
    assert "<Test>" not in page, "Unescaped angle brackets must not appear in XHTML"


# ---------------------------------------------------------------------------
# build_epub — error handling
# ---------------------------------------------------------------------------


def test_build_epub_raises_epub_error_on_write_failure(tmp_path: Path) -> None:
    """A disk-write failure must be converted to EpubError, not a raw OSError.

    Without this conversion, a disk-full condition would show the user a Python
    traceback instead of an actionable error message.
    """
    from unittest.mock import patch
    conference = _make_conference(n_talks=1)
    output = tmp_path / "test.epub"

    with patch("zipfile.ZipFile", side_effect=OSError("disk full")):
        with pytest.raises(EpubError, match="Failed to write EPUB"):
            build_epub(conference, tmp_path, output)


# ---------------------------------------------------------------------------
# build_epub — ZIP integrity (#90)
# ---------------------------------------------------------------------------


def test_build_epub_zip_passes_testzip(tmp_path: Path) -> None:
    """A freshly built EPUB must pass zipfile.testzip() with no corrupt entries."""
    conference = _make_conference(n_talks=3)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    with zipfile.ZipFile(output) as zf:
        result = zf.testzip()
    assert result is None, (
        f"zipfile.testzip() should return None for a valid ZIP, got: {result!r}"
    )


# ---------------------------------------------------------------------------
# build_epub — image compression (#91)
# ---------------------------------------------------------------------------


def test_build_epub_images_stored_not_deflated(tmp_path: Path) -> None:
    """JPEG images in the EPUB must be stored (ZIP_STORED), not Deflate-compressed."""
    conference = _make_conference(n_talks=2)
    output = tmp_path / "test.epub"

    # Add a cover image and speaker photos so we have something to check
    images_dir = tmp_path
    cover_path = images_dir / "cover.jpg"
    _make_jpeg(cover_path, size=(800, 450))

    speakers_dir = images_dir / "speakers"
    speakers_dir.mkdir()
    for talk in conference.talks:
        photo_path = speakers_dir / f"{talk.talk_index:03d}-{talk.speaker.replace(' ', '-')}.jpg"
        _make_jpeg(photo_path, size=(300, 300))
        talk.speaker_image_url = "https://www.churchofjesuschrist.org/imgs/test"

    conference.cover_image_url = "https://www.churchofjesuschrist.org/imgs/cover"

    build_epub(conference, images_dir, output)

    with zipfile.ZipFile(output) as zf:
        for info in zf.infolist():
            if info.filename.startswith("images/"):
                assert info.compress_type == zipfile.ZIP_STORED, (
                    f"Image {info.filename!r} should be ZIP_STORED, "
                    f"got compress_type={info.compress_type}"
                )
            elif info.filename.endswith((".xhtml", ".css", ".opf", ".xml")):
                assert info.compress_type == zipfile.ZIP_DEFLATED, (
                    f"Text file {info.filename!r} should be ZIP_DEFLATED, "
                    f"got compress_type={info.compress_type}"
                )


# ---------------------------------------------------------------------------
# _sanitize_transcript — footnote markers (#92)
# ---------------------------------------------------------------------------


def test_sanitize_transcript_materializes_data_value_for_empty_markers() -> None:
    """Empty elements with data-value must have their number materialized as text content.

    The Church website uses CSS content: attr(data-value) to render footnote
    numbers. The <sup> has no text content — only data-value. After stripping
    data-*, the number must still be visible.
    """
    html = '<p>Text.<sup class="marker" data-value="1"></sup></p>'
    result = _sanitize_transcript(html)
    assert ">1<" in result, (
        f"data-value '1' must be materialized as text content, got: {result!r}"
    )
    assert "data-value" not in result, (
        f"data-value attribute must still be stripped after materialization, got: {result!r}"
    )


def test_sanitize_transcript_preserves_existing_text_over_data_value() -> None:
    """If an element already has text content, data-value must not overwrite it."""
    html = '<span data-value="X">Already has text</span>'
    result = _sanitize_transcript(html)
    assert "Already has text" in result, "Existing text content must be preserved"
    # data-value should be stripped, but it should NOT replace the existing text
    assert ">X<" not in result, (
        f"data-value 'X' must not overwrite existing text content, got: {result!r}"
    )


# ---------------------------------------------------------------------------
# build_epub — EPUB semantics (#93, #94)
# ---------------------------------------------------------------------------


def test_nav_has_landmarks(tmp_path: Path) -> None:
    """nav.xhtml must contain a landmarks nav with cover, toc, and bodymatter entries."""
    conference = _make_conference(n_talks=2)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)

    nav = _epub_read(output, "nav.xhtml").decode()
    assert 'epub:type="landmarks"' in nav, (
        "nav.xhtml must have a landmarks nav section"
    )
    assert 'epub:type="cover"' in nav, "Landmarks must include a cover entry"
    assert 'epub:type="toc"' in nav, "Landmarks must include a toc entry"
    assert 'epub:type="bodymatter"' in nav, "Landmarks must include a bodymatter entry"


def test_cover_page_has_epub_type_cover(tmp_path: Path) -> None:
    """cover.xhtml body must have epub:type="cover"."""
    conference = _make_conference(n_talks=1)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)

    cover = _epub_read(output, "text/cover.xhtml").decode()
    assert 'epub:type="cover"' in cover, (
        f"cover.xhtml body must have epub:type='cover', got: {cover[:300]!r}"
    )


def test_talk_page_has_epub_type_chapter(tmp_path: Path) -> None:
    """Talk XHTML bodies must have epub:type="chapter"."""
    conference = _make_conference(n_talks=1)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)

    with zipfile.ZipFile(output) as zf:
        talk_files = [n for n in zf.namelist() if n.startswith("text/talk-")]
        assert talk_files, "Expected at least one talk XHTML file"
        talk_content = zf.read(talk_files[0]).decode()

    assert 'epub:type="chapter"' in talk_content, (
        f"Talk page body must have epub:type='chapter', got: {talk_content[:300]!r}"
    )


# ---------------------------------------------------------------------------
# build_epub — cleanup (#96, #97, #98)
# ---------------------------------------------------------------------------


def test_sanitize_transcript_strips_class_attributes() -> None:
    """Web CSS class names must be stripped — they have no EPUB stylesheet rules."""
    html = (
        '<p class="body-block">Text</p>'
        '<div class="imageWrapper-wTPPD"><ul class="bullet"><li>item</li></ul></div>'
    )
    result = _sanitize_transcript(html)
    assert "class=" not in result, (
        f"All class attributes must be stripped, got: {result!r}"
    )
    assert "Text" in result, "Paragraph text content must be preserved"
    assert "item" in result, "List item content must be preserved"


def test_build_epub_opf_modified_is_recent(tmp_path: Path) -> None:
    """dcterms:modified in content.opf must reflect the actual build time."""
    from datetime import datetime, timezone

    # Capture window; strip microseconds since the OPF timestamp has second precision
    before = datetime.now(timezone.utc).replace(microsecond=0)
    conference = _make_conference(n_talks=1)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)
    after = datetime.now(timezone.utc).replace(microsecond=0)

    opf = _epub_read(output, "content.opf").decode()
    import re
    match = re.search(r"<meta property=\"dcterms:modified\">([^<]+)</meta>", opf)
    assert match, f"dcterms:modified not found in OPF: {opf[:500]!r}"
    modified = datetime.fromisoformat(match.group(1).replace("Z", "+00:00"))
    assert before <= modified <= after, (
        f"dcterms:modified {modified.isoformat()} must be between "
        f"{before.isoformat()} and {after.isoformat()}"
    )


def test_build_epub_css_has_transcript_img_rule(tmp_path: Path) -> None:
    """The EPUB stylesheet must have a .transcript img rule to constrain inline images."""
    conference = _make_conference(n_talks=1)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)

    css = _epub_read(output, "style.css").decode()
    assert ".transcript img" in css, (
        "style.css must include a .transcript img rule for inline image sizing"
    )
    assert "max-width" in css, "The .transcript img rule must include max-width"


# ---------------------------------------------------------------------------
# _make_portrait_cover (#95)
# ---------------------------------------------------------------------------


def test_make_portrait_cover_produces_portrait_dimensions(tmp_path: Path) -> None:
    """Portrait cover output must be taller than wide (height > width)."""
    src = tmp_path / "landscape.jpg"
    _make_jpeg(src, size=(800, 450))
    result = _make_portrait_cover(src)

    with Image.open(io.BytesIO(result)) as img:
        assert img.height > img.width, (
            f"Portrait cover must be taller than wide, got {img.width}x{img.height}"
        )


def test_make_portrait_cover_output_is_jpeg(tmp_path: Path) -> None:
    """Portrait cover must be a valid JPEG."""
    src = tmp_path / "landscape.jpg"
    _make_jpeg(src, size=(800, 450))
    result = _make_portrait_cover(src)

    assert result[:2] == b"\xff\xd8", (
        "Portrait cover bytes must start with JPEG magic bytes"
    )


def test_make_portrait_cover_uses_expected_dimensions(tmp_path: Path) -> None:
    """Portrait cover must use the defined canvas dimensions (1200x1800)."""
    from gencon_audiobook.epub_builder import _COVER_HEIGHT, _COVER_WIDTH

    src = tmp_path / "landscape.jpg"
    _make_jpeg(src, size=(800, 450))
    result = _make_portrait_cover(src)

    with Image.open(io.BytesIO(result)) as img:
        assert img.width == _COVER_WIDTH, (
            f"Cover width must be {_COVER_WIDTH}, got {img.width}"
        )
        assert img.height == _COVER_HEIGHT, (
            f"Cover height must be {_COVER_HEIGHT}, got {img.height}"
        )


# ---------------------------------------------------------------------------
# build_epub — session divider pages (#99)
# ---------------------------------------------------------------------------


def test_build_epub_has_session_divider_pages(tmp_path: Path) -> None:
    """Each session must have a dedicated divider page in the EPUB."""
    conference = _make_conference(n_talks=4)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)

    names = _epub_names(output)
    session_pages = [n for n in names if n.startswith("text/session-")]
    assert len(session_pages) == len(conference.sessions), (
        f"Expected {len(conference.sessions)} session pages, got {session_pages}"
    )


def test_nav_session_headers_link_to_divider_pages(tmp_path: Path) -> None:
    """Session header links in nav.xhtml must point to session divider pages, not talks."""
    conference = _make_conference(n_talks=4)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)

    nav = _epub_read(output, "nav.xhtml").decode()
    assert "text/session-" in nav, (
        "nav.xhtml session headers must link to session divider pages"
    )


def test_build_epub_spine_includes_session_pages(tmp_path: Path) -> None:
    """The OPF spine must include session divider pages before their talks."""
    conference = _make_conference(n_talks=4)
    output = tmp_path / "test.epub"
    build_epub(conference, tmp_path, output)

    opf = _epub_read(output, "content.opf").decode()
    assert "session-001" in opf, (
        "content.opf spine must include session-001 divider page"
    )

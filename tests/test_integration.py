"""End-to-end integration tests.

These tests exercise the full audio and EPUB pipelines using real ffmpeg and
real file I/O. They do NOT make network requests — all fixtures are generated
programmatically.

Requires ffmpeg on PATH. Excluded from normal CI.

Run manually:
    pytest tests/test_integration.py -v -m integration
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from mutagen.mp4 import MP4
from PIL import Image

from gencon_audiobook.audio import build_m4b
from gencon_audiobook.epub_builder import build_epub
from gencon_audiobook.models import Conference, Session, Talk
from gencon_audiobook.utils import sanitize_filename


# ---------------------------------------------------------------------------
# ffmpeg availability
# ---------------------------------------------------------------------------


def _find_ffmpeg() -> Path | None:
    w = shutil.which("ffmpeg")
    return Path(w) if w else None


def _find_ffprobe(ffmpeg: Path) -> Path | None:
    cand = ffmpeg.parent / f"ffprobe{ffmpeg.suffix}"
    if cand.exists():
        return cand
    w = shutil.which("ffprobe")
    return Path(w) if w else None


_FFMPEG = _find_ffmpeg()
_FFPROBE = _find_ffprobe(_FFMPEG) if _FFMPEG else None

requires_ffmpeg = pytest.mark.skipif(
    _FFMPEG is None or _FFPROBE is None,
    reason="ffmpeg/ffprobe not available on PATH",
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _make_silent_mp3(path: Path, duration: float = 3.0) -> None:
    """Write a short silent MP3 to path using ffmpeg."""
    assert _FFMPEG is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(_FFMPEG),
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=mono:sample_rate=44100",
            "-t", str(duration),
            "-acodec", "libmp3lame",
            "-ab", "128k",
            "-y", str(path),
        ],
        check=True,
        capture_output=True,
    )


def _make_jpeg(path: Path, size: tuple[int, int] = (200, 200)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, color="gray")
    img.save(path, format="JPEG")


def _build_conference(tmp_path: Path) -> Conference:
    """Build a 3-session / 7-talk conference with all fixtures on disk.

    Intentional edge cases baked in:
    - Talk 4 has no speaker photo (tests the graceful-skip path in build_epub)
    - Talk 3 transcript contains an external link and a <script> tag
      (tests _sanitize_transcript in build_epub)
    - All talks have 3-second silent MP3s (fast to convert with ffmpeg)
    - Speaker photos are 500 x 600 px — wider than the 300 px cap in _resize_photo
    """
    sessions_data = [
        ("Saturday Morning Session", [
            ("Opening Hymn", "President Eyring"),
            ("Sustaining Church Leaders", "President Oaks"),
            ("On the Covenant Path", "Elder Bednar"),
        ]),
        ("Saturday Afternoon Session", [
            ("The Restoration Continues", "Elder Holland"),
            ("Faith in Every Footstep", "Elder Rasband"),  # no photo
        ]),
        ("Sunday Morning Session", [
            ("The Living Christ", "President Nelson"),
            ("Closing Remarks", "President Eyring"),
        ]),
    ]

    sessions: list[Session] = []
    talk_index = 1
    for snum, (session_name, talks_data) in enumerate(sessions_data, start=1):
        talks: list[Talk] = []
        for tnum, (title, speaker) in enumerate(talks_data, start=1):
            transcript = (
                f"<p>This is the transcript for {title}.</p>"
                + (
                    '<p><a href="https://evil.com/track">External link</a>.</p>'
                    "<script>alert('xss')</script>"
                    if talk_index == 3
                    else ""
                )
            )
            talks.append(Talk(
                title=title,
                speaker=speaker,
                talk_url=f"https://www.churchofjesuschrist.org/t{talk_index}",
                mp3_url=f"https://assets.churchofjesuschrist.org/{talk_index:03d}.mp3",
                transcript_html=transcript,
                speaker_image_url=f"https://assets.churchofjesuschrist.org/img{talk_index}.jpg",
                session_name=session_name,
                session_number=snum,
                talk_number=tnum,
                talk_index=talk_index,
            ))
            talk_index += 1
        sessions.append(Session(name=session_name, number=snum, talks=talks))

    conference = Conference(
        title="April 2024 General Conference",
        year=2024,
        month=4,
        cover_image_url="https://assets.churchofjesuschrist.org/cover.jpg",
        sessions=sessions,
        conference_url="https://www.churchofjesuschrist.org/study/general-conference/2024/04",
    )

    # MP3 files
    for talk in conference.talks:
        mp3 = tmp_path / "audio" / f"{talk.talk_index:03d}-{sanitize_filename(talk.title)}.mp3"
        _make_silent_mp3(mp3, duration=3.0)

    # Cover image
    _make_jpeg(tmp_path / "cover.jpg", size=(400, 600))

    # Speaker photos — skip Talk 4 intentionally
    skip_index = 4
    for talk in conference.talks:
        if talk.talk_index == skip_index:
            continue
        photo = (
            tmp_path / "speakers"
            / f"{talk.talk_index:03d}-{sanitize_filename(talk.speaker)}.jpg"
        )
        _make_jpeg(photo, size=(500, 600))  # wider than 300 px to exercise resize

    return conference


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------


@pytest.mark.integration
@requires_ffmpeg
def test_full_pipeline_m4b_and_epub(tmp_path: Path) -> None:
    """Full pipeline: fixtures -> build_m4b -> build_epub.

    Verifies structural and content correctness of both outputs without
    touching the network. This is the single end-to-end smoke test that
    catches regressions in the assembly logic of both builders.

    Checks:
    - m4b exists and is non-trivial in size
    - duration_seconds is set on every talk (required for chapter timing)
    - chapter count matches talk count
    - chapter titles all contain ' -- ' separator
    - last chapter end time is within 1s of total m4b duration (alignment)
    - cover art is embedded in the m4b
    - no intermediate .m4a files remain after build
    - EPUB exists and is a valid ZIP
    - mimetype is the first entry and is stored uncompressed
    - required structural files are present
    - one XHTML page per talk
    - all session names and talk titles appear in nav.xhtml
    - copyright page contains Intellectual Reserve notice
    - transcripts appear in talk pages; XSS is stripped; external URLs removed
    - correct number of speaker photos embedded (one missing = n-1)
    - embedded photos are <= 300 px wide (resize was applied)
    - CSS has no color/background-color/font-family declarations
    - OPF spine order matches talk order
    - m4b chapter count equals EPUB talk page count (cross-output consistency)
    """
    conference = _build_conference(tmp_path)
    all_talks = conference.talks
    n_talks = len(all_talks)

    m4b_path = tmp_path / "April 2024 General Conference.m4b"
    epub_path = tmp_path / "April 2024 General Conference.epub"
    audio_dir = tmp_path / "audio"
    cover_path = tmp_path / "cover.jpg"

    # -------------------------------------------------------------------------
    # Phase 1: Build m4b
    # -------------------------------------------------------------------------

    build_m4b(
        conference=conference,
        audio_dir=audio_dir,
        output_path=m4b_path,
        cover_path=cover_path,
        ffmpeg_path=_FFMPEG,
        ffprobe_path=_FFPROBE,
        bitrate="64k",
        sample_rate=44100,
    )

    assert m4b_path.exists(), "m4b output must be created"
    assert m4b_path.stat().st_size > 10_000, "m4b must be at least 10 KB"

    # duration_seconds must be set for every talk (used in FFMETADATA1 chapter offsets)
    for talk in all_talks:
        assert talk.duration_seconds > 0, (
            f"duration_seconds must be set after build_m4b, "
            f"got {talk.duration_seconds} for '{talk.title}'"
        )

    # Chapter count
    probe = subprocess.run(
        [str(_FFPROBE), "-v", "quiet", "-print_format", "json",
         "-show_chapters", str(m4b_path)],
        capture_output=True, text=True, check=True,
    )
    chapters = json.loads(probe.stdout).get("chapters", [])
    assert len(chapters) == n_talks, (
        f"Expected {n_talks} chapters, got {len(chapters)}"
    )

    # Chapter title format
    for ch in chapters:
        title = ch.get("tags", {}).get("title", "")
        assert " -- " in title, f"Chapter title must contain ' -- ', got: {title!r}"

    # Chapter boundary alignment (catches the ADTS duration-estimation bug)
    dur_probe = subprocess.run(
        [str(_FFPROBE), "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(m4b_path)],
        capture_output=True, text=True, check=True,
    )
    total_s = float(dur_probe.stdout.strip())
    last_end_s = float(chapters[-1]["end_time"])
    assert abs(last_end_s - total_s) < 1.0, (
        f"Last chapter end ({last_end_s:.3f}s) must be within 1s of "
        f"total duration ({total_s:.3f}s)"
    )

    # Cover art embedded
    mp4 = MP4(str(m4b_path))
    assert mp4.tags is not None and "covr" in mp4.tags, \
        "Cover art must be embedded in the m4b"

    # No leftover intermediate .m4a files
    leftover_m4a = list(audio_dir.glob("*.m4a"))
    assert leftover_m4a == [], (
        f"Intermediate .m4a files must be deleted: {[f.name for f in leftover_m4a]}"
    )

    # -------------------------------------------------------------------------
    # Phase 2: Build EPUB
    # -------------------------------------------------------------------------

    build_epub(
        conference=conference,
        images_dir=tmp_path,
        output_path=epub_path,
    )

    assert epub_path.exists(), "EPUB output must be created"
    assert epub_path.stat().st_size > 5_000, "EPUB must be at least 5 KB"

    import re as _re

    with zipfile.ZipFile(epub_path) as zf:
        names = set(zf.namelist())
        namelist = zf.namelist()

        # mimetype first and uncompressed
        assert namelist[0] == "mimetype", \
            f"First ZIP entry must be 'mimetype', got {namelist[0]!r}"
        assert zf.getinfo("mimetype").compress_type == zipfile.ZIP_STORED, \
            "mimetype must be ZIP_STORED (not deflated)"
        assert zf.read("mimetype").decode("ascii") == "application/epub+zip"

        # Required structural files
        for required in (
            "META-INF/container.xml", "content.opf", "nav.xhtml",
            "style.css", "text/cover.xhtml", "text/copyright.xhtml",
        ):
            assert required in names, f"Required EPUB file missing: {required!r}"

        # One XHTML page per talk
        talk_pages = [n for n in names if n.startswith("text/talk-")]
        assert len(talk_pages) == n_talks, (
            f"Expected {n_talks} talk pages, got {len(talk_pages)}"
        )

        # nav.xhtml contains all sessions and talk titles
        nav = zf.read("nav.xhtml").decode("utf-8")
        for session in conference.sessions:
            assert session.name in nav, \
                f"Session '{session.name}' missing from nav.xhtml"
        for talk in all_talks:
            assert talk.title in nav, \
                f"Talk title '{talk.title}' missing from nav.xhtml"

        # Copyright page
        cp = zf.read("text/copyright.xhtml").decode("utf-8")
        assert "Intellectual Reserve" in cp, \
            "Copyright page must contain 'Intellectual Reserve'"
        assert "2024" in cp, "Copyright page must include the conference year"
        assert "unofficial" in cp.lower(), \
            "Copyright page must include the unofficial disclaimer"

        # Talk pages: transcript present; XSS stripped; external URLs removed
        for talk in all_talks:
            fname = f"text/talk-{talk.talk_index:03d}-{sanitize_filename(talk.title)}.xhtml"
            page = zf.read(fname).decode("utf-8")
            assert talk.title in page, \
                f"Talk title missing from {fname}"
            assert talk.speaker in page, \
                f"Speaker name missing from {fname}"
            assert "<script>" not in page, \
                f"<script> tag must not appear in {fname} (sanitizer failed)"
            assert "evil.com" not in page, \
                f"External URL must not appear in {fname} (sanitizer failed)"

        # Cover image
        assert "images/cover.jpg" in names, "Cover image must be embedded"

        # Speaker photos: all except Talk 4 (skip_index=4) are present
        spk_images = [n for n in names if n.startswith("images/spk-")]
        expected_photos = n_talks - 1  # one intentionally missing
        assert len(spk_images) == expected_photos, (
            f"Expected {expected_photos} speaker photos, got {len(spk_images)}"
        )

        # Photos resized to <= 300 px wide
        for img_name in spk_images:
            img_bytes = zf.read(img_name)
            img = Image.open(io.BytesIO(img_bytes))
            assert img.width <= 300, (
                f"{img_name}: width {img.width} exceeds 300 px cap"
            )

        # CSS compliance (epub-style.md rules)
        css = zf.read("style.css").decode("utf-8")
        css_stripped = _re.sub(r"/\*.*?\*/", "", css, flags=_re.DOTALL)
        assert not _re.search(r"\bcolor\s*:", css_stripped), \
            "CSS must not contain color declarations"
        assert not _re.search(r"\bbackground(-color)?\s*:", css_stripped), \
            "CSS must not contain background-color declarations"
        assert not _re.search(r"\bfont-family\s*:", css_stripped), \
            "CSS must not contain font-family declarations"

        # OPF spine order matches talk order
        opf = zf.read("content.opf").decode("utf-8")
        spine_ids = _re.findall(r'idref="(talk-\d+)"', opf)
        expected_spine = [f"talk-{t.talk_index:03d}" for t in all_talks]
        assert spine_ids == expected_spine, (
            f"OPF spine order mismatch.\nExpected: {expected_spine}\nGot: {spine_ids}"
        )

    # -------------------------------------------------------------------------
    # Phase 3: Cross-output consistency
    # -------------------------------------------------------------------------

    epub_talk_count = len([
        n for n in zipfile.ZipFile(epub_path).namelist()
        if n.startswith("text/talk-")
    ])
    assert len(chapters) == epub_talk_count, (
        f"m4b chapter count ({len(chapters)}) must equal EPUB talk page count "
        f"({epub_talk_count})"
    )

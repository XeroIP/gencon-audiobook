"""Unit tests for downloader.py — all HTTP mocked with the responses library."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
import requests
import responses as rsps_lib
from PIL import Image

from gencon_audiobook.downloader import (
    DownloadError,
    _audio_path,
    _speaker_path,
    cleanup_tmp_files,
    download_file,
)
from gencon_audiobook.models import Conference, Session, Talk

_ALLOWED_URL = "https://assets.churchofjesuschrist.org/test.mp3"
_ALLOWED_IMG = "https://assets.churchofjesuschrist.org/test.jpg"
_BLOCKED_URL = "https://evil.example.com/test.mp3"


def _make_session() -> requests.Session:
    return requests.Session()


def _small_mp3() -> bytes:
    """Minimal bytes standing in for an MP3."""
    return b"\xff\xfb\x00"


def _jpeg_bytes(color: str = "red", size: tuple[int, int] = (10, 10)) -> bytes:
    """Generate a small in-memory JPEG."""
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _png_bytes(color: str = "blue", size: tuple[int, int] = (10, 10)) -> bytes:
    """Generate a small in-memory PNG."""
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# download_file — success
# ---------------------------------------------------------------------------


@rsps_lib.activate
def test_download_file_success(tmp_path: Path) -> None:
    content = _small_mp3()
    rsps_lib.add(rsps_lib.GET, _ALLOWED_URL, body=content, status=200)

    dest = tmp_path / "audio" / "001-test.mp3"
    download_file(_ALLOWED_URL, dest, _make_session())

    assert dest.exists(), "Destination file should exist after download"
    assert dest.read_bytes() == content, "Destination content should match server response"
    assert not dest.with_suffix(dest.suffix + ".tmp").exists(), ".tmp file should be cleaned up"


@rsps_lib.activate
def test_download_file_creates_parent_directory(tmp_path: Path) -> None:
    rsps_lib.add(rsps_lib.GET, _ALLOWED_URL, body=_small_mp3(), status=200)

    dest = tmp_path / "audio" / "nested" / "001-test.mp3"
    download_file(_ALLOWED_URL, dest, _make_session())

    assert dest.exists(), "Download should create parent directories as needed"


# ---------------------------------------------------------------------------
# download_file — skip existing
# ---------------------------------------------------------------------------


@rsps_lib.activate
def test_download_file_skips_existing(tmp_path: Path) -> None:
    content = _small_mp3()
    rsps_lib.add(rsps_lib.HEAD, _ALLOWED_URL, status=200, headers={"Content-Length": str(len(content))})

    dest = tmp_path / "001-test.mp3"
    dest.write_bytes(content)  # pre-existing correct file

    download_file(_ALLOWED_URL, dest, _make_session())

    get_calls = [c for c in rsps_lib.calls if c.request.method == "GET"]
    assert len(get_calls) == 0, "GET should not be issued when file is already complete"


@rsps_lib.activate
def test_download_file_redownloads_if_size_differs(tmp_path: Path) -> None:
    content = _small_mp3()
    rsps_lib.add(rsps_lib.HEAD, _ALLOWED_URL, status=200, headers={"Content-Length": "999"})
    rsps_lib.add(rsps_lib.GET, _ALLOWED_URL, body=content, status=200)

    dest = tmp_path / "001-test.mp3"
    dest.write_bytes(b"\x00")  # wrong size

    download_file(_ALLOWED_URL, dest, _make_session())

    assert dest.read_bytes() == content, "File should be replaced when sizes differ"


# ---------------------------------------------------------------------------
# download_file — retries
# ---------------------------------------------------------------------------


@rsps_lib.activate
def test_download_file_retries_on_503(tmp_path: Path) -> None:
    content = _small_mp3()
    rsps_lib.add(rsps_lib.HEAD, _ALLOWED_URL, status=404)  # triggers re-download
    rsps_lib.add(rsps_lib.GET, _ALLOWED_URL, status=503)
    rsps_lib.add(rsps_lib.GET, _ALLOWED_URL, status=503)
    rsps_lib.add(rsps_lib.GET, _ALLOWED_URL, body=content, status=200)

    dest = tmp_path / "001-test.mp3"
    download_file(_ALLOWED_URL, dest, _make_session(), retries=3)

    assert dest.exists(), "File should exist after eventual success"
    assert dest.read_bytes() == content


@rsps_lib.activate
def test_download_file_raises_after_max_retries(tmp_path: Path) -> None:
    rsps_lib.add(rsps_lib.HEAD, _ALLOWED_URL, status=404)
    for _ in range(4):  # initial + 3 retries
        rsps_lib.add(rsps_lib.GET, _ALLOWED_URL, status=500)

    dest = tmp_path / "001-test.mp3"
    with pytest.raises(DownloadError):
        download_file(_ALLOWED_URL, dest, _make_session(), retries=3)


# ---------------------------------------------------------------------------
# download_file — URL validation
# ---------------------------------------------------------------------------


def test_download_file_rejects_non_allowlisted_url(tmp_path: Path) -> None:
    dest = tmp_path / "001-test.mp3"
    with pytest.raises(ValueError, match="not on allowlist"):
        download_file(_BLOCKED_URL, dest, _make_session())


# ---------------------------------------------------------------------------
# download_file — tmp cleanup on failure
# ---------------------------------------------------------------------------


@rsps_lib.activate
def test_download_file_cleans_up_tmp_on_failure(tmp_path: Path) -> None:
    rsps_lib.add(rsps_lib.HEAD, _ALLOWED_URL, status=404)
    for _ in range(4):
        rsps_lib.add(rsps_lib.GET, _ALLOWED_URL, status=500)

    dest = tmp_path / "001-test.mp3"
    with pytest.raises(DownloadError):
        download_file(_ALLOWED_URL, dest, _make_session(), retries=3)

    tmp = dest.with_suffix(dest.suffix + ".tmp")
    assert not tmp.exists(), ".tmp file should not exist after failure"


# ---------------------------------------------------------------------------
# cleanup_tmp_files
# ---------------------------------------------------------------------------


def test_cleanup_tmp_files_removes_tmp(tmp_path: Path) -> None:
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "001-test.mp3.tmp").write_bytes(b"partial")
    (tmp_path / "cover.jpg.tmp").write_bytes(b"partial")

    cleanup_tmp_files(tmp_path)

    assert not (tmp_path / "audio" / "001-test.mp3.tmp").exists()
    assert not (tmp_path / "cover.jpg.tmp").exists()


def test_cleanup_tmp_files_leaves_complete_files(tmp_path: Path) -> None:
    complete = tmp_path / "001-test.mp3"
    complete.write_bytes(b"complete")
    cleanup_tmp_files(tmp_path)
    assert complete.exists(), "Complete files should not be removed"


# ---------------------------------------------------------------------------
# Image conversion
# ---------------------------------------------------------------------------


@rsps_lib.activate
def test_download_conference_converts_images_to_jpeg(tmp_path: Path) -> None:
    from gencon_audiobook.downloader import _download_image

    png_data = _png_bytes()
    rsps_lib.add(rsps_lib.GET, _ALLOWED_IMG, body=png_data, status=200)

    dest = tmp_path / "cover.jpg"
    _download_image(_ALLOWED_IMG, dest, _make_session())

    assert dest.exists(), "Image file should be saved"
    img = Image.open(dest)
    assert img.format == "JPEG", f"Expected JPEG output, got {img.format!r}"


@rsps_lib.activate
def test_download_image_skips_existing(tmp_path: Path) -> None:
    from gencon_audiobook.downloader import _download_image

    dest = tmp_path / "cover.jpg"
    dest.write_bytes(_jpeg_bytes())

    _download_image(_ALLOWED_IMG, dest, _make_session())

    assert len(rsps_lib.calls) == 0, "No HTTP request should be made for an existing image"


def test_download_image_rejects_non_allowlisted_url(tmp_path: Path) -> None:
    from gencon_audiobook.downloader import _download_image

    dest = tmp_path / "cover.jpg"
    with pytest.raises(ValueError, match="not on allowlist"):
        _download_image("https://evil.example.com/photo.jpg", dest, _make_session())


# ---------------------------------------------------------------------------
# Filename helpers
# ---------------------------------------------------------------------------


def test_audio_path_format(tmp_path: Path) -> None:
    talk = Talk(
        title="Welcome to Conference",
        speaker="John Smith",
        talk_url="https://www.churchofjesuschrist.org/t",
        talk_index=3,
    )
    path = _audio_path(tmp_path, talk)
    assert path.name == "003-Welcome to Conference.mp3", f"Unexpected name: {path.name!r}"
    assert path.parent == tmp_path / "audio"


def test_speaker_path_format(tmp_path: Path) -> None:
    talk = Talk(
        title="Test",
        speaker="Dallin H. Oaks",
        talk_url="https://www.churchofjesuschrist.org/t",
        talk_index=1,
    )
    path = _speaker_path(tmp_path, talk)
    assert path.name == "001-Dallin H. Oaks.jpg", f"Unexpected name: {path.name!r}"
    assert path.parent == tmp_path / "speakers"

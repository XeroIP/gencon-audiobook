"""Tests for sanitize_filename and validate_url."""

from __future__ import annotations

import pytest

from gencon_audiobook.utils import sanitize_filename, validate_url


# ---------------------------------------------------------------------------
# sanitize_filename
# ---------------------------------------------------------------------------


def test_sanitize_filename_clean_input_unchanged():
    result = sanitize_filename("April 2024 General Conference")
    assert result == "April 2024 General Conference", f"Expected unchanged, got {result!r}"


def test_sanitize_filename_replaces_unsafe_chars():
    result = sanitize_filename("hello/world:foo?bar")
    assert "/" not in result, f"Slash not removed: {result!r}"
    assert ":" not in result, f"Colon not removed: {result!r}"
    assert "?" not in result, f"Question mark not removed: {result!r}"


def test_sanitize_filename_collapses_consecutive_underscores():
    result = sanitize_filename("hello///world")
    assert "__" not in result, f"Consecutive underscores remain: {result!r}"


def test_sanitize_filename_strips_leading_trailing_underscores():
    result = sanitize_filename("___hello___")
    assert not result.startswith("_"), f"Leading underscore remains: {result!r}"
    assert not result.endswith("_"), f"Trailing underscore remains: {result!r}"


def test_sanitize_filename_strips_leading_trailing_spaces():
    result = sanitize_filename("  hello  ")
    assert not result.startswith(" "), f"Leading space remains: {result!r}"
    assert not result.endswith(" "), f"Trailing space remains: {result!r}"


def test_sanitize_filename_unicode_replaced():
    result = sanitize_filename("caf\u00e9 talk")
    assert "\u00e9" not in result, f"Unicode char not replaced: {result!r}"


def test_sanitize_filename_empty_string_returns_unnamed():
    result = sanitize_filename("")
    assert result == "unnamed", f"Expected 'unnamed', got {result!r}"


def test_sanitize_filename_only_unsafe_chars_returns_unnamed():
    result = sanitize_filename("///???!!!")
    assert result == "unnamed", f"Expected 'unnamed', got {result!r}"


def test_sanitize_filename_truncates_at_200_chars():
    long_name = "a" * 300
    result = sanitize_filename(long_name)
    assert len(result) <= 200, f"Result exceeds 200 chars: {len(result)}"


def test_sanitize_filename_path_traversal_dotdot_returns_unnamed():
    result = sanitize_filename("..")
    assert result == "unnamed", f"Expected 'unnamed' for '..', got {result!r}"


def test_sanitize_filename_path_traversal_with_slashes():
    result = sanitize_filename("../../etc/passwd")
    assert "/" not in result, f"Slash remains: {result!r}"
    assert not result.startswith(".."), f"Result starts with '..': {result!r}"
    assert result != "..", f"Result is bare '..': {result!r}"


def test_sanitize_filename_null_byte_returns_unnamed():
    result = sanitize_filename("hello\x00world")
    assert "\x00" not in result, f"Null byte remains: {result!r}"


def test_sanitize_filename_preserves_dots_dashes_underscores():
    result = sanitize_filename("file-name_v1.2")
    assert result == "file-name_v1.2", f"Expected unchanged, got {result!r}"


def test_sanitize_filename_already_clean_name():
    result = sanitize_filename("Talk Title Here")
    assert result == "Talk Title Here", f"Expected unchanged, got {result!r}"


# ---------------------------------------------------------------------------
# validate_url
# ---------------------------------------------------------------------------


def test_validate_url_exact_domain():
    url = "https://churchofjesuschrist.org/study/general-conference"
    assert validate_url(url) is True, f"Expected allowed URL to pass: {url!r}"


def test_validate_url_ldscdn_subdomain():
    url = "https://media.ldscdn.org/audio/general-conference/talk.mp3"
    assert validate_url(url) is True, f"Expected allowed URL to pass: {url!r}"


def test_validate_url_ldscdn_deeper_subdomain():
    url = "https://cdn2.ldscdn.org/audio/talk.mp3"
    assert validate_url(url) is True, f"Expected allowed URL to pass: {url!r}"


def test_validate_url_media_churchofjesuschrist():
    url = "https://media.churchofjesuschrist.org/audio/talk.mp3"
    assert validate_url(url) is True, f"Expected allowed URL to pass: {url!r}"


def test_validate_url_media_numbered_subdomain():
    url = "https://media2.churchofjesuschrist.org/audio/talk.mp3"
    assert validate_url(url) is True, f"Expected allowed URL to pass: {url!r}"


def test_validate_url_www_subdomain():
    url = "https://www.churchofjesuschrist.org/study/general-conference"
    assert validate_url(url) is True, f"Expected allowed URL to pass: {url!r}"


def test_validate_url_assets_subdomain():
    url = "https://assets.churchofjesuschrist.org/abc123-32k-en.mp3"
    assert validate_url(url) is True, f"Expected allowed URL to pass: {url!r}"


def test_validate_url_non_allowlisted_domain_rejected():
    url = "https://evil.com/malware.mp3"
    assert validate_url(url) is False, f"Expected non-allowlisted URL to be rejected: {url!r}"


def test_validate_url_lookalike_domain_rejected():
    url = "https://churchofjesuschrist.org.evil.com/path"
    assert validate_url(url) is False, f"Expected lookalike domain to be rejected: {url!r}"


def test_validate_url_http_scheme_allowed():
    # scheme is not restricted — only hostname matters
    url = "http://churchofjesuschrist.org/path"
    assert validate_url(url) is True, f"Expected http:// scheme to be allowed: {url!r}"


def test_validate_url_malformed_url_returns_false():
    url = "not a url at all"
    assert validate_url(url) is False, f"Expected malformed URL to return False: {url!r}"


def test_validate_url_empty_string_returns_false():
    assert validate_url("") is False, "Expected empty string to return False"


def test_validate_url_bare_ldscdn_without_subdomain_rejected():
    # ldscdn.org without a subdomain is not in the allowlist (pattern is *.ldscdn.org)
    url = "https://ldscdn.org/audio/talk.mp3"
    assert validate_url(url) is False, f"Expected bare ldscdn.org to be rejected: {url!r}"


def test_validate_url_never_raises_on_garbage_input():
    # Must not raise for any input
    for bad in ["://", "http://", "\x00", "a" * 10000]:
        try:
            validate_url(bad)
        except Exception as exc:
            pytest.fail(f"validate_url raised for input {bad!r}: {exc}")

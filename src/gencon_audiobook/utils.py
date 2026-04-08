"""Filename sanitization and URL validation utilities."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_SAFE_CHARS = re.compile(r"[^a-zA-Z0-9 ._-]")
_MULTI_UNDERSCORE = re.compile(r"_+")
_MAX_FILENAME_LENGTH = 200

_ALLOWED_HOSTNAMES = re.compile(
    r"""
    ^(
        churchofjesuschrist\.org          |   # exact domain
        [a-z0-9-]+\.ldscdn\.org           |   # *.ldscdn.org
        media[a-z0-9-]*\.churchofjesuschrist\.org  # media*.churchofjesuschrist.org
    )$
    """,
    re.VERBOSE | re.IGNORECASE,
)


def sanitize_filename(name: str) -> str:
    """Return a safe filename derived from name.

    Replaces characters outside [a-zA-Z0-9 ._-] with underscores, collapses
    consecutive underscores, strips leading/trailing underscores and spaces,
    and truncates to 200 characters. Never returns a string that could be used
    for path traversal.

    Args:
        name: Raw string to sanitize.

    Returns:
        A safe filename string. Returns "unnamed" if the result would be empty.
    """
    # Replace unsafe characters with underscores
    result = _SAFE_CHARS.sub("_", name)
    # Collapse consecutive underscores
    result = _MULTI_UNDERSCORE.sub("_", result)
    # Strip leading/trailing underscores, spaces, and dots. Dots are included to prevent
    # hidden files on Unix and leading-dot traversal patterns like ../ after a path join.
    result = result.strip(" _.")
    # Truncate
    result = result[:_MAX_FILENAME_LENGTH]
    # Strip again after truncation in case we cut mid-sequence
    result = result.strip(" _.")

    # Reject path traversal patterns — these should never survive the above,
    # but be explicit as a defence-in-depth measure
    if not result or result == ".." or result.startswith("/") or "\x00" in result:
        return "unnamed"

    return result or "unnamed"


def validate_url(url: str) -> bool:
    """Return True if url is on the allowed domain list, False otherwise.

    Allowed domains:
    - churchofjesuschrist.org
    - *.ldscdn.org
    - media*.churchofjesuschrist.org

    Never raises — invalid or malformed URLs return False.

    Args:
        url: URL string to validate.

    Returns:
        True if the URL hostname matches the allowlist, False otherwise.
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        result = bool(_ALLOWED_HOSTNAMES.match(hostname))
        if not result:
            logger.debug("URL rejected by allowlist: %s", url)
        return result
    except Exception:
        logger.debug("URL validation failed (malformed URL): %s", url)
        return False

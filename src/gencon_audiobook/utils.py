"""Filename sanitization, URL validation, and shared HTTP session utilities."""

from __future__ import annotations

import logging
import re
import threading
from typing import cast
from urllib.parse import urlparse

import requests

from . import __version__

logger = logging.getLogger(__name__)

# Single source of truth for the User-Agent string sent with every HTTP request.
# Both scraper.py and downloader.py import this constant so version updates
# only need to happen in one place (__version__ in __init__.py).
USER_AGENT = (
    f"gencon-audiobook/{__version__}"
    " (open source; github.com/XeroIP/gencon-audiobook)"
)

_SAFE_CHARS = re.compile(r"[^a-zA-Z0-9 ._-]")
_MULTI_UNDERSCORE = re.compile(r"_+")
_MAX_FILENAME_LENGTH = 200

_ALLOWED_HOSTNAMES = re.compile(
    r"""
    ^(
        churchofjesuschrist\.org                    |   # bare domain
        [a-z0-9][a-z0-9-]*\.churchofjesuschrist\.org |   # any *.churchofjesuschrist.org subdomain
        [a-z0-9][a-z0-9-]*\.ldscdn\.org               # any *.ldscdn.org subdomain
    )$
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Thread-local storage so each worker thread gets its own requests.Session.
# requests.Session is NOT thread-safe; sharing one across threads causes
# intermittent connection errors and garbled responses. Shared across all
# modules' ThreadPoolExecutor workers since a Session is generic — no module
# needs its own cache.
_thread_locals: threading.local = threading.local()


def make_session() -> requests.Session:
    """Create a requests.Session with the project User-Agent header."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def get_thread_session() -> requests.Session:
    """Return the requests.Session for the current thread, creating it on first access.

    Each thread gets its own Session because requests.Session is not thread-safe.
    """
    if not hasattr(_thread_locals, "session"):
        _thread_locals.session = make_session()
    # threading.local attributes are typed as Any; cast makes the return type explicit.
    return cast(requests.Session, _thread_locals.session)


def sanitize_filename(name: str) -> str:
    """Return a safe filename derived from name.

    Replaces spaces with hyphens, replaces characters outside [a-zA-Z0-9 ._-]
    with underscores, collapses consecutive underscores, strips leading/trailing
    underscores and spaces, and truncates to 200 characters. Never returns a
    string that could be used for path traversal.

    Spaces are replaced with hyphens (not underscores) so that filenames used
    in EPUB IRI path segments are valid without percent-encoding (epubcheck
    PKG-010).

    Args:
        name: Raw string to sanitize.

    Returns:
        A safe filename string. Returns "unnamed" if the result would be empty.
    """
    # Replace spaces with hyphens before other transformations so EPUB IRI
    # path segments contain no spaces (epubcheck PKG-010, RSC-020).
    result = name.replace(" ", "-")
    # Replace unsafe characters with underscores
    result = _SAFE_CHARS.sub("_", result)
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
    - *.churchofjesuschrist.org

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
    except (AttributeError, TypeError, ValueError):
        logger.debug("URL validation failed (malformed URL): %s", url)
        return False

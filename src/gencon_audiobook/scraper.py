"""Scrape conference listings and talk pages from churchofjesuschrist.org."""

from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, cast  # JSON decode returns Any; no narrower type available
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup, Tag

from .models import Conference, InlineImage, Session, Talk
from .progress import shared_console as console
from .progress import standard_progress
from .utils import USER_AGENT, validate_url

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.churchofjesuschrist.org"
_ARCHIVE_PATH = "/study/general-conference"

_REQUEST_DELAY = 0.5
_CONNECT_TIMEOUT = 15
_READ_TIMEOUT = 30
_MAX_RETRIES = 3
_MIN_RESPONSE_LENGTH = 1000   # responses shorter than this are suspiciously small
_CLOUDFLARE_PAGE_LENGTH = 5000  # challenge pages are tiny; real pages are much larger

# Matches /study/general-conference/YYYY/MM (conference listing URL)
# Allows trailing query strings like ?lang=eng
_CONFERENCE_URL_RE = re.compile(r"/study/general-conference/(\d{4})/(\d{2})(?:\?|$)")

# Matches /study/general-conference/YYYYYYYY (decade-range index, e.g. 20202024)
_DECADE_RANGE_RE = re.compile(r"/study/general-conference/(\d{4})(\d{4})$")


def _upgrade_iiif(url: str) -> str:
    """Rewrite IIIF size segment to request 800px-wide image.

    The Church website serves images via an IIIF Image API endpoint. The
    og:image and img src tags use small thumbnail sizes (e.g., 250px). This
    function upgrades those to 800px for better quality in the EPUB output.
    Both percent-encoded (%21...%2C) and plain (!N,) forms are handled.
    Non-IIIF URLs pass through unchanged.

    Args:
        url: Original image URL.

    Returns:
        URL with IIIF size parameter upgraded to 800px, or original URL unchanged.
    """
    url = re.sub(r"/full/%21\d+%2C/", "/full/%21800%2C/", url)
    url = re.sub(r"/full/!\d+,/", "/full/!800,/", url)
    return url

# Matches any /study/general-conference/YYYY/MM/slug URL — talk and session links
# alike. The character class [a-z0-9][-a-z0-9]* covers modern unhyphenated slugs
# ("11oaks") and older hyphenated ones ("the-work-moves-forward"). Talk vs.
# session is determined by DOM position in _sessions_from_html, not URL pattern.
_CONF_URL_RE = re.compile(
    r"/study/general-conference/\d{4}/\d{2}/[a-z0-9][-a-z0-9]*(?:\?|$)",
    re.IGNORECASE,
)


# Cache of parsed RobotFileParser objects, keyed by scheme+host (e.g. "https://www.churchofjesuschrist.org")
_robots_cache: dict[str, RobotFileParser | None] = {}

# Scans raw bytes for <meta charset="..."> or <meta http-equiv="Content-Type" content="...charset=...">
# Operates on bytes so it works before any decoding decision is made.
_META_CHARSET_RE = re.compile(
    rb'<meta[^>]+(?:charset=["\']?([a-zA-Z0-9_-]+)|content=["\'][^"\']*charset=([a-zA-Z0-9_-]+))',
    re.IGNORECASE,
)


def _get_robots(http: requests.Session, base_url: str) -> RobotFileParser | None:
    """Fetch and parse robots.txt for the given base URL, with session-level caching.

    Args:
        http: Requests session to use for the fetch.
        base_url: Scheme + host (e.g. "https://www.churchofjesuschrist.org").

    Returns:
        Parsed RobotFileParser, or None if robots.txt could not be fetched.
    """
    if base_url in _robots_cache:
        return _robots_cache[base_url]

    robots_url = f"{base_url}/robots.txt"
    try:
        response = http.get(robots_url, timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT))
        response.raise_for_status()
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        _robots_cache[base_url] = parser
        logger.debug("Fetched robots.txt from %s", robots_url)
    except (requests.RequestException, OSError) as exc:
        logger.warning("Could not fetch robots.txt from %s: %s — proceeding anyway", robots_url, exc)
        _robots_cache[base_url] = None

    return _robots_cache[base_url]


def _check_robots(http: requests.Session, url: str) -> None:
    """Raise ScraperError if url is disallowed by the site's robots.txt.

    Args:
        http: Requests session to use if robots.txt needs fetching.
        url: Full URL to check.

    Raises:
        ScraperError: if the URL is explicitly disallowed for our User-Agent.
    """
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    parser = _get_robots(http, base)
    if parser is not None and not parser.can_fetch(USER_AGENT, url):
        raise ScraperError(
            f"URL disallowed by robots.txt: {url}. "
            "If you believe this is an error, open a GitHub issue: "
            "github.com/XeroIP/gencon-audiobook"
        )


@dataclass
class ConferenceRef:
    """A reference to a General Conference (title + URL), used for listing conferences.

    Args:
        title: Display title, e.g. "April 2024 General Conference".
        url: Full URL to the conference listing page.
        year: Four-digit year.
        month: 4 for April, 10 for October.
    """

    title: str
    url: str
    year: int
    month: int


class ScraperError(Exception):
    """User-facing scraper failure with an actionable message."""


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _make_http_session() -> requests.Session:
    """Create a requests.Session with the project User-Agent header."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _decode_response(response: requests.Response) -> str:
    """Decode an HTTP response with robust multi-language encoding detection.

    Detection priority:
    1. Charset declared in the Content-Type header (most authoritative).
    2. Charset in an HTML <meta charset> tag, scanned from raw bytes before
       any decoding — language-agnostic and works for all scripts.
    3. Encoding detected by charset-normalizer / chardet (bundled with requests).
    4. UTF-8 as a final fallback (the internet default).

    Decodes with errors='replace' so a single malformed byte never crashes
    the scraper. Replacement characters are logged at DEBUG level.

    Args:
        response: A completed requests.Response object.

    Returns:
        The response body as a decoded string.
    """
    content_type = response.headers.get("content-type", "")
    if "charset=" in content_type.lower():
        # Server declared encoding explicitly — trust it.
        encoding: str = response.encoding or "utf-8"
    else:
        # No charset in headers; scan the first 4 KB of raw bytes for a meta tag.
        head = response.content[:4096]
        meta_match = _META_CHARSET_RE.search(head)
        if meta_match:
            raw_charset = meta_match.group(1) or meta_match.group(2)
            encoding = raw_charset.decode("ascii", errors="replace")
            logger.debug("Encoding from meta tag for %s: %s", response.url, encoding)
        elif response.apparent_encoding:
            # charset-normalizer / chardet statistical detection.
            encoding = response.apparent_encoding
            logger.debug("Encoding detected for %s: %s", response.url, encoding)
        else:
            encoding = "utf-8"

    try:
        text = response.content.decode(encoding, errors="replace")
    except LookupError:
        logger.debug(
            "Unknown encoding %r for %s; falling back to UTF-8", encoding, response.url
        )
        text = response.content.decode("utf-8", errors="replace")

    if "\ufffd" in text:
        logger.debug(
            "Replacement characters in response from %s (encoding: %s) "
            "— some non-ASCII content may be garbled",
            response.url,
            encoding,
        )

    return text


def _fetch(http: requests.Session, url: str, delay: float = _REQUEST_DELAY) -> str:
    """Fetch url, returning the response body as text.

    Validates the URL against the allowlist, retries on transient errors with
    exponential backoff, and detects bot-protection responses.

    Args:
        http: requests.Session to use.
        url: URL to fetch. Must pass validate_url().
        delay: Seconds to wait after a successful fetch.

    Returns:
        Response body as a string.

    Raises:
        ScraperError: on allowlist violation, bot detection, or exhausted retries.
    """
    if not validate_url(url):
        raise ScraperError(f"URL not on allowlist: {url}")

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        if attempt > 0:
            wait = 2 ** (attempt - 1)
            logger.debug("Retry %d for %s (waiting %ds)", attempt, url, wait)
            time.sleep(wait)

        try:
            logger.debug("Fetching: %s", url)
            response = http.get(url, timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT))

            if response.status_code == 403:
                # 403 is a permanent block — do not retry.
                raise ScraperError(
                    "Access was blocked (HTTP 403). "
                    "The website may be blocking automated access. "
                    "Try again later or open a GitHub issue if this persists: "
                    "github.com/XeroIP/gencon-audiobook"
                )

            if response.status_code == 429:
                # 429 is a transient rate-limit signal — respect Retry-After if present,
                # otherwise fall through to raise_for_status() which triggers the retry loop.
                retry_after = response.headers.get("Retry-After")
                if retry_after is not None:
                    try:
                        wait_override = int(retry_after)
                        logger.warning(
                            "Rate limited (HTTP 429). Retry-After: %ds — waiting before retry.",
                            wait_override,
                        )
                        time.sleep(wait_override)
                    except ValueError:
                        pass  # non-integer Retry-After (date format) — ignore, let backoff handle it

            response.raise_for_status()

            body = _decode_response(response)
            if len(body) < _MIN_RESPONSE_LENGTH:
                logger.warning("Suspiciously short response for %s (%d chars)", url, len(body))
            if "cloudflare" in body.lower() or (
                "challenge" in body.lower() and len(body) < _CLOUDFLARE_PAGE_LENGTH
            ):
                raise ScraperError(
                    "Access was blocked by the website. This may be temporary. "
                    "Wait a few minutes and try again, or open a GitHub issue if this persists: "
                    "github.com/XeroIP/gencon-audiobook"
                )

            time.sleep(delay)
            return body

        except ScraperError:
            raise
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning("Request error for %s: %s", url, exc)

    raise ScraperError(
        f"Could not connect after {_MAX_RETRIES} retries. Check your internet connection. "
        f"Last error: {last_exc}"
    ) from last_exc


# ---------------------------------------------------------------------------
# JSON state extraction
# ---------------------------------------------------------------------------


def _parse_initial_state(html: str) -> dict[str, Any]:
    """Extract and parse window.__INITIAL_STATE__ from a page's HTML.

    The Church website embeds application state as a base64-encoded JSON string
    assigned to window.__INITIAL_STATE__ in a <script> tag. Decode and
    json.loads() only — never execute.

    Args:
        html: Full HTML of a Church website page.

    Returns:
        Parsed dict, or empty dict if not found or unparseable.
    """
    # Match both quoted base64 string and raw JSON object forms
    match = re.search(r'window\.__INITIAL_STATE__\s*=\s*"([^"]+)"', html)
    if match:
        # Base64-encoded JSON string
        try:
            json_bytes = base64.b64decode(match.group(1))
            return cast(dict[str, Any], json.loads(json_bytes))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.debug("Failed to base64-decode __INITIAL_STATE__: %s", exc)

    # Fallback: raw JSON object (some pages may not encode it)
    match = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*)", html, re.DOTALL)
    if match:
        json_str = match.group(1)
        end = json_str.find("</script>")
        if end > 0:
            json_str = json_str[:end].rstrip("; \n\r\t")
        try:
            return cast(dict[str, Any], json.loads(json_str))
        except json.JSONDecodeError as exc:
            logger.debug("Failed to parse __INITIAL_STATE__ as raw JSON: %s", exc)

    return {}


# ---------------------------------------------------------------------------
# Conference archive parsing
# ---------------------------------------------------------------------------


def parse_conference_archive(html: str) -> list[ConferenceRef]:
    """Parse the list of available conferences from the archive page HTML.

    Tries the __INITIAL_STATE__ JSON first; falls back to href pattern matching.

    Args:
        html: HTML content of the conference archive page.

    Returns:
        ConferenceRef list ordered most-recent first.

    Raises:
        ScraperError: if no conferences can be parsed.
    """
    refs: list[ConferenceRef] = []

    # Primary: __INITIAL_STATE__ JSON
    state = _parse_initial_state(html)
    if state:
        refs = _refs_from_state(state)
        if refs:
            logger.debug("Archive JSON selector: %d conferences", len(refs))

    # Fallback: href link scanning
    if not refs:
        logger.warning("Archive JSON selector found nothing; falling back to href scan")
        refs = _refs_from_html(html)
        if refs:
            logger.debug("Archive HTML fallback: %d conferences", len(refs))

    if not refs:
        raise ScraperError(
            "Could not find any conference listings. The website structure may have changed. "
            "Please open a GitHub issue at github.com/XeroIP/gencon-audiobook."
        )

    # Sort most-recent first, deduplicate
    refs.sort(key=lambda r: (r.year, r.month), reverse=True)
    seen: set[tuple[int, int]] = set()
    unique: list[ConferenceRef] = []
    for ref in refs:
        key = (ref.year, ref.month)
        if key not in seen:
            seen.add(key)
            unique.append(ref)

    return unique


def _refs_from_state(state: dict[str, Any]) -> list[ConferenceRef]:
    """Extract ConferenceRef list from __INITIAL_STATE__ dict.

    The archive JSON groups conferences into: recent direct links (YYYY/MM) and
    decade-range index pages (e.g. /study/general-conference/20202024). Decade
    ranges are expanded into individual YYYY/MM refs rather than requiring
    additional HTTP fetches.
    """
    refs: list[ConferenceRef] = []
    library = state.get("library", {})
    archive = library.get("/eng/general-conference", {})
    sections = archive.get("sections", [])

    for section in sections:
        for entry in section.get("entries", []):
            uri = entry.get("uri", "")
            # Direct conference URL: /study/general-conference/YYYY/MM
            m = _CONFERENCE_URL_RE.search(uri)
            if m:
                year, month = int(m.group(1)), int(m.group(2))
                title = entry.get("title", "")
                if not title:
                    title = f"{_month_name(month)} {year} General Conference"
                elif "General Conference" not in title:
                    title = f"{title} General Conference"
                refs.append(ConferenceRef(
                    title=title,
                    url=urljoin(_BASE_URL, uri.split("?")[0]),
                    year=year,
                    month=month,
                ))
                continue

            # Decade-range index: /study/general-conference/YYYYYYYY (e.g. 20202024)
            refs.extend(_expand_decade_range(uri))

    return refs


def _expand_decade_range(uri: str) -> list[ConferenceRef]:
    """Expand a decade-range URI into individual April/October ConferenceRefs.

    The archive page groups older conferences into decade ranges like
    /study/general-conference/20202024. Expand each into one ref per
    April and October within the range — no additional HTTP fetch required.

    Args:
        uri: URI like /study/general-conference/20202024.

    Returns:
        List of ConferenceRefs, or empty list if uri is not a decade range.
    """
    m = _DECADE_RANGE_RE.search(uri)
    if not m:
        return []
    start_year, end_year = int(m.group(1)), int(m.group(2))
    refs: list[ConferenceRef] = []
    for year in range(start_year, end_year + 1):
        for month in (4, 10):
            month_nm = _month_name(month)
            refs.append(ConferenceRef(
                title=f"{month_nm} {year} General Conference",
                url=f"{_BASE_URL}/study/general-conference/{year}/{month:02d}",
                year=year,
                month=month,
            ))
    return refs


def _refs_from_html(html: str) -> list[ConferenceRef]:
    """Fallback: scan <a href> links for conference URL patterns."""
    refs: list[ConferenceRef] = []
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = _CONFERENCE_URL_RE.search(href)
        if m:
            year, month = int(m.group(1)), int(m.group(2))
            title = a.get_text(strip=True)
            if not title:
                title = f"{_month_name(month)} {year} General Conference"
            elif "General Conference" not in title:
                title = f"{title} General Conference"
            refs.append(ConferenceRef(
                title=title,
                url=urljoin(_BASE_URL, href.split("?")[0]),
                year=year,
                month=month,
            ))
    return refs


# ---------------------------------------------------------------------------
# Conference listing parsing
# ---------------------------------------------------------------------------


def parse_conference_listing(html: str) -> list[Session]:
    """Parse sessions and talk stubs from a conference listing page.

    Tries the __INITIAL_STATE__ JSON first; falls back to HTML traversal.

    Args:
        html: HTML content of the conference listing page.

    Returns:
        List of Session objects with Talk stubs (title, speaker, talk_url populated).

    Raises:
        ScraperError: if no talks can be parsed.
    """
    sessions: list[Session] = []

    # Primary: __INITIAL_STATE__ JSON
    state = _parse_initial_state(html)
    if state:
        sessions = _sessions_from_state(state)
        if sessions:
            logger.debug("Listing JSON selector: %d sessions", len(sessions))

    # Fallback: HTML traversal
    if not sessions:
        logger.debug("Listing JSON selector found nothing; falling back to HTML traversal")
        sessions = _sessions_from_html(html)
        if sessions:
            logger.debug("Listing HTML fallback: %d sessions", len(sessions))

    if not sessions:
        raise ScraperError(
            "Could not find any talks on the conference page. The website may have changed. "
            "Please open a GitHub issue at github.com/XeroIP/gencon-audiobook."
        )

    return sessions


def _sessions_from_state(state: dict[str, Any]) -> list[Session]:
    """Extract sessions from __INITIAL_STATE__ for the conference listing page.

    Older conferences (pre-2020) have duplicate sections in the JSON: the real
    sessions appear first, then a second set of unnamed sections that repeat the
    same talks with a session landing page prepended. We deduplicate by tracking
    seen talk URLs — any entry whose URL was already claimed by an earlier session
    is skipped, and sections that produce zero new talks are dropped entirely.
    """
    library = state.get("library", {})
    sessions: list[Session] = []
    seen_urls: set[str] = set()

    # Find the library key that matches a conference listing URL
    for key, value in library.items():
        if not _CONFERENCE_URL_RE.search(key):
            continue
        raw_sections = value.get("sections", [])
        for i, section in enumerate(raw_sections, start=1):
            name = section.get("title")
            if not name:
                # Older conferences have unnamed duplicate sections that repeat
                # every talk from a named session plus a session landing page.
                # Skip them — real sessions always have titles in the JSON.
                logger.debug("Skipping unnamed JSON section %d (likely duplicate)", i)
                continue
            talks: list[Talk] = []
            for entry in section.get("entries", []):
                uri = entry.get("uri", "")
                # Skip entries that don't look like conference sub-pages
                if not _CONF_URL_RE.search(uri):
                    continue
                talk_url = urljoin(_BASE_URL, uri.split("?")[0])
                if talk_url in seen_urls:
                    continue
                title = entry.get("title", "")
                speaker = entry.get("subtitle", "") or entry.get("author", "")
                if title:
                    seen_urls.add(talk_url)
                    talks.append(Talk(title=title, speaker=speaker, talk_url=talk_url))
            if talks:
                sessions.append(Session(name=name, number=i, talks=talks))
        if sessions:
            break

    return sessions


def _extract_talk_title(a: Tag) -> str:
    """Extract talk title from a talk <a> element.

    Current site structure (CSS-module class names may change):
        <a><div><p>Title</p><p class="subtitle-*">Speaker</p></div></a>

    Primary: first <p> child of the first <div> inside <a>.
    Fallbacks: <p class="title"> inside <h4>, then <h4> text.
    """
    div = a.find("div")
    if isinstance(div, Tag):
        ps = div.find_all("p", recursive=False)
        if ps:
            return str(ps[0].get_text(strip=True))
    h4 = a.find("h4")
    if isinstance(h4, Tag):
        p = h4.find("p", class_="title")
        if isinstance(p, Tag):
            return p.get_text(strip=True)
        return h4.get_text(strip=True)
    p = a.find("p", class_="title")
    if isinstance(p, Tag):
        return p.get_text(strip=True)
    return ""


def _extract_talk_speaker(a: Tag) -> str:
    """Extract speaker name from a talk <a> element.

    Current site structure (CSS-module class names may change):
        <a><div><p>Title</p><p class="subtitle-*">Speaker</p></div></a>

    Primary: second <p> child of the first <div> inside <a>.
    Fallbacks: <p class="primaryMeta">, <h6> text.
    """
    div = a.find("div")
    if isinstance(div, Tag):
        ps = div.find_all("p", recursive=False)
        if len(ps) >= 2:
            return str(ps[1].get_text(strip=True))
    el = a.find("p", class_="primaryMeta")
    if isinstance(el, Tag):
        return el.get_text(strip=True)
    h6 = a.find("h6")
    if isinstance(h6, Tag):
        return h6.get_text(strip=True)
    return ""


def _sessions_from_html(html: str) -> list[Session]:
    """Fallback: parse sessions and talk stubs from conference listing HTML.

    Observed structure on the Church website (CSS-module class names may change):

        <li>                                     <- session LI
          <a class="sectionTitle-*">Saturday Morning Session</a>
          <ul>                                   <- talks for this session
            <li>
              <a href="/study/general-conference/YYYY/MM/talk-id">
                <div class="itemTitle-*">
                  <p>Talk Title</p>
                  <p class="subtitle-*">Speaker Name</p>
                </div>
              </a>
            </li>
            ...
          </ul>
        </li>

    Session <li> elements are identified by having a direct-child <ul> that contains
    at least one conference link. This approach works across conference eras without
    needing to bootstrap a walk from a specific link position.
    """
    soup = BeautifulSoup(html, "html.parser")

    conf_links = soup.find_all("a", href=_CONF_URL_RE)
    if not conf_links:
        return []

    # Find session <li> elements directly: a <li> is a session if it has a
    # direct-child <ul> that contains at least one conference link.
    # Bootstrapping from conf_links[0] fails for older conferences where the
    # first link in document order is a session landing page (in the outer UL),
    # not a talk (in the inner UL).
    session_lis: list[Tag] = []
    for li in soup.find_all("li"):
        if not isinstance(li, Tag):
            continue
        sub_ul = li.find("ul", recursive=False)
        if isinstance(sub_ul, Tag) and sub_ul.find("a", href=_CONF_URL_RE):
            session_lis.append(li)

    sessions: list[Session] = []
    session_number = 0

    if session_lis:
        for li in session_lis:
            sub_ul = li.find("ul", recursive=False)
            if not isinstance(sub_ul, Tag):
                continue

            # Session name: direct-child <a> of the session <li> (the session heading link).
            # URL matching is not used — all conf URLs look alike; DOM position distinguishes
            # session <li> from talk <li>. Fall back to <h4> for older HTML that uses headings.
            session_name: str | None = None
            for a in li.find_all("a", recursive=False):
                session_name = a.get_text(strip=True)
                break
            if not session_name:
                h4 = li.find("h4", recursive=False)
                if isinstance(h4, Tag):
                    session_name = h4.get_text(strip=True)
            if not session_name:
                # Unnamed session LIs are duplicates — the site renders each session twice:
                # once with a direct-child <a> holding the name, once with a <div> and no name.
                # Skip the unnamed copies.
                continue

            talks: list[Talk] = []
            for talk_li in sub_ul.find_all("li", recursive=False):
                talk_a = talk_li.find("a", href=_CONF_URL_RE)
                if not talk_a:
                    continue
                title = _extract_talk_title(talk_a)
                speaker = _extract_talk_speaker(talk_a)
                if title:
                    talk_url = urljoin(_BASE_URL, talk_a["href"].split("?")[0])
                    talks.append(Talk(title=title, speaker=speaker, talk_url=talk_url))

            if talks:
                session_number += 1
                sessions.append(Session(name=session_name, number=session_number, talks=talks))

    # Fallback: no session structure detected — put all talks in one session
    if not sessions:
        logger.warning("No session structure detected; grouping all talks under one session")
        all_talks: list[Talk] = []
        for a in conf_links:
            title = _extract_talk_title(a)
            speaker = _extract_talk_speaker(a)
            if title:
                talk_url = urljoin(_BASE_URL, a["href"].split("?")[0])
                all_talks.append(Talk(title=title, speaker=speaker, talk_url=talk_url))
        if all_talks:
            sessions.append(Session(name="General Conference", number=1, talks=all_talks))

    return sessions


# ---------------------------------------------------------------------------
# Talk page parsing
# ---------------------------------------------------------------------------


def parse_talk_page(html: str, talk_url: str) -> dict:
    """Extract mp3_url, transcript_html, speaker_image_url, speaker, and inline_images from a talk page.

    Args:
        html: HTML content of the individual talk page.
        talk_url: URL of this talk page (used only for logging).

    Returns:
        Dict with keys: mp3_url, transcript_html, speaker_image_url, speaker,
        inline_images. String values may be None if not found; inline_images
        is always a list (possibly empty).
    """
    soup = BeautifulSoup(html, "html.parser")
    result: dict = {
        "mp3_url": None,
        "transcript_html": None,
        "speaker_image_url": None,
        "speaker": None,
        "inline_images": [],
    }

    # MP3 URL — primary: reader.contentStore[*].meta.audio[0].mediaUrl in __INITIAL_STATE__
    # The Church website embeds the audio URL in JS state; the HTML player is rendered client-side.
    state = _parse_initial_state(html)
    content_store = state.get("reader", {}).get("contentStore", {})
    for _key, entry in content_store.items():
        audio_list = entry.get("meta", {}).get("audio", [])
        if audio_list:
            media_url = audio_list[0].get("mediaUrl", "")
            if media_url and validate_url(media_url):
                result["mp3_url"] = media_url
                logger.debug("mp3_url (contentStore): %s", media_url)
                break

    if not result["mp3_url"]:
        # Fallback A: <source type="audio/mpeg"> inside a <video>
        source = soup.find("source", {"type": "audio/mpeg"})
        if isinstance(source, Tag):
            src_val = source.get("src")
            if isinstance(src_val, str) and validate_url(src_val):
                result["mp3_url"] = src_val
                logger.debug("mp3_url (video source): %s", result["mp3_url"])

    if not result["mp3_url"]:
        logger.warning("MP3 selectors failed for %s, trying href/src scan", talk_url)
        # Fallback B: any <a> or <source> with an .mp3 URL on an allowed domain
        for tag in soup.find_all(["a", "source"]):
            if not isinstance(tag, Tag):
                continue
            href_val = tag.get("href") or tag.get("src") or ""
            href = str(href_val)
            if href.endswith(".mp3") and validate_url(href):
                result["mp3_url"] = href
                logger.debug("mp3_url (href/src scan): %s", href)
                break

    # Transcript — primary: div.body-block
    body = soup.find("div", class_="body-block")
    if body:
        result["transcript_html"] = str(body)
        logger.debug("transcript (primary div.body-block): %d chars", len(result["transcript_html"] or ""))

    if not result["transcript_html"]:
        logger.warning("Primary transcript selector failed for %s, trying fallback", talk_url)
        # Fallback 1: article[data-content-type]
        article = soup.find("article", attrs={"data-content-type": True})
        if article:
            result["transcript_html"] = str(article)
        else:
            # Fallback 2: any article
            article = soup.find("article")
            if article:
                result["transcript_html"] = str(article)

    # Inline images — extract from transcript body before speaker search.
    # Images use srcset-only (no src) in the Church site's responsive markup,
    # so we parse srcset to find the canonical URL. Skip the speaker photo
    # (found later) by only considering images inside div.body-block.
    if body and isinstance(body, Tag):
        seen_asset_ids: set[str] = set()
        for img in body.find_all("img"):
            if not isinstance(img, Tag):
                continue
            asset_id: str = str(img.get("data-assetid") or img.get("data-img-id") or "")
            # Derive from URL path if data attributes are missing
            src_raw = str(img.get("src") or "")
            srcset_raw = str(img.get("srcset") or "")
            # Pick best URL: prefer a direct src, otherwise parse srcset
            best_url: str | None = None
            if src_raw and validate_url(src_raw) and "/imgs/" in src_raw:
                best_url = src_raw
            elif srcset_raw:
                # srcset format: "url1 60w, url2 100w, ..." — pick largest width
                candidates: list[tuple[int, str]] = []
                for part in srcset_raw.split(","):
                    part = part.strip()
                    if not part:
                        continue
                    pieces = part.split()
                    if len(pieces) >= 2:
                        cand_url = pieces[0]
                        width_str = pieces[1].rstrip("w")
                        try:
                            width = int(width_str)
                        except ValueError:
                            width = 0
                        if validate_url(cand_url) and "/imgs/" in cand_url:
                            candidates.append((width, cand_url))
                if candidates:
                    best_url = max(candidates, key=lambda t: t[0])[1]
            if not best_url:
                continue
            if not asset_id:
                # Derive from the URL's path segment after /imgs/
                path_parts = best_url.split("/imgs/")
                asset_id = path_parts[1].split("/")[0] if len(path_parts) > 1 else ""
            if not asset_id or asset_id in seen_asset_ids:
                continue
            seen_asset_ids.add(asset_id)
            alt = str(img.get("alt") or "")
            result["inline_images"].append(InlineImage(url=best_url, alt=alt, asset_id=asset_id))
            logger.debug("Found inline image: asset_id=%s url=%s", asset_id, best_url)

    # Speaker name — primary: p.author-name
    author_el = soup.find("p", class_="author-name")
    if author_el:
        text = author_el.get_text(strip=True)
        # Strip "Presented by" / "By" prefixes
        text = re.sub(r"^(presented\s+by\s+|by\s+)", "", text, flags=re.IGNORECASE).strip()
        result["speaker"] = text
        logger.debug("speaker (primary p.author-name): %s", text)

    if not result["speaker"]:
        # Fallback: [class*="author-name"]
        for el in soup.find_all(class_=re.compile("author.?name", re.IGNORECASE)):
            text = el.get_text(strip=True)
            text = re.sub(r"^(presented\s+by\s+|by\s+)", "", text, flags=re.IGNORECASE).strip()
            if text:
                result["speaker"] = text
                break

    # Speaker photo — primary: img whose src contains /imgs/ and is on an allowed domain
    for img in soup.find_all("img", src=True):
        if not isinstance(img, Tag):
            continue
        src = img.get("src")
        if isinstance(src, str) and "/imgs/" in src and validate_url(src):
            result["speaker_image_url"] = _upgrade_iiif(src)
            logger.debug("speaker_image_url (primary /imgs/): %s", result["speaker_image_url"])
            break

    if not result["speaker_image_url"]:
        # Fallback: og:image meta tag
        og = soup.find("meta", property="og:image")
        if isinstance(og, Tag):
            content = og.get("content")
            if isinstance(content, str) and validate_url(content):
                result["speaker_image_url"] = _upgrade_iiif(content)

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reset_robots_cache() -> None:
    """Clear the cached robots.txt parsers (for testing only)."""
    _robots_cache.clear()


def fetch_available_conferences() -> list[ConferenceRef]:
    """Fetch all available conferences from the archive page.

    Returns:
        List of ConferenceRef ordered most-recent first.

    Raises:
        ScraperError: if the archive page cannot be fetched or parsed.
    """
    http = _make_http_session()
    url = _BASE_URL + _ARCHIVE_PATH
    _check_robots(http, url)
    html = _fetch(http, url)
    return parse_conference_archive(html)


def scrape_conference(conference_url: str) -> Conference:
    """Scrape a single conference: parse listing, then fetch each talk page.

    Populates all Talk fields including mp3_url, transcript_html,
    speaker_image_url, session_number, talk_number, and talk_index.
    Talks that fail individually are logged and skipped.

    Args:
        conference_url: URL of the conference listing page.

    Returns:
        Fully populated Conference object.

    Raises:
        ScraperError: if the conference page fails or zero valid talks are found.
    """
    http = _make_http_session()
    _check_robots(http, conference_url)

    # Fetch and parse conference listing
    listing_html = _fetch(http, conference_url)
    sessions = parse_conference_listing(listing_html)

    # Parse year/month/title from URL
    m = _CONFERENCE_URL_RE.search(conference_url)
    year = int(m.group(1)) if m else 0
    month = int(m.group(2)) if m else 0
    title = f"{_month_name(month)} {year} General Conference"

    # Extract cover image
    soup = BeautifulSoup(listing_html, "html.parser")
    cover_image_url = _find_cover_image(soup)

    # Assign talk_index and session metadata
    talk_index = 1
    for session_obj in sessions:
        for j, talk in enumerate(session_obj.talks, start=1):
            talk.session_number = session_obj.number
            talk.session_name = session_obj.name
            talk.talk_number = j
            talk.talk_index = talk_index
            talk_index += 1

    # Fetch each talk page
    all_talks = [t for s in sessions for t in s.talks]
    valid_count = 0
    skipped: list[Talk] = []

    console.print(f"Scraping: {title}")
    scrape_progress = standard_progress()
    with scrape_progress:
        task = scrape_progress.add_task("Scraping talks", total=len(all_talks))
        for i, talk in enumerate(all_talks, start=1):
            scrape_progress.update(task, description=talk.title[:60])
            logger.debug("Scraping talk %d/%d: %s", i, len(all_talks), talk.title)
            try:
                talk_html = _fetch(http, talk.talk_url)
                data = parse_talk_page(talk_html, talk.talk_url)

                # Use speaker from talk page if listing didn't provide one
                if not talk.speaker and data["speaker"]:
                    talk.speaker = data["speaker"]

                talk.mp3_url = data["mp3_url"]
                talk.transcript_html = data["transcript_html"]
                talk.speaker_image_url = data["speaker_image_url"]
                talk.inline_images = data["inline_images"]

                # Validate required fields
                missing = []
                if not talk.title:
                    missing.append("title")
                if not talk.speaker:
                    missing.append("speaker")
                if not talk.mp3_url or not validate_url(talk.mp3_url):
                    missing.append("mp3_url")

                if missing:
                    logger.warning(
                        "Talk at %s missing required fields: %s — skipping",
                        talk.talk_url,
                        ", ".join(missing),
                    )
                    skipped.append(talk)
                else:
                    valid_count += 1

            except ScraperError as exc:
                logger.error("Failed to scrape talk %s: %s", talk.talk_url, exc)
                skipped.append(talk)
            finally:
                scrape_progress.advance(task)

    if skipped:
        logger.warning("%d talk(s) skipped due to missing fields or errors", len(skipped))

    if valid_count == 0:
        raise ScraperError(
            "No valid talks found. The website structure may have changed. "
            "Please open a GitHub issue at github.com/XeroIP/gencon-audiobook."
        )

    return Conference(
        title=title,
        year=year,
        month=month,
        cover_image_url=cover_image_url,
        sessions=sessions,
        conference_url=conference_url,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _month_name(month: int) -> str:
    """Return the English month name for General Conference months (4 or 10)."""
    return {4: "April", 10: "October"}.get(month, f"Month {month}")


def _find_cover_image(soup: BeautifulSoup) -> str | None:
    """Try to find a conference cover image URL from a parsed page.

    Upgrades IIIF-style size parameters to 800px wide so the cover is
    suitable for an ebook cover rather than a social-sharing thumbnail.
    """
    # Primary: og:image meta tag
    og = soup.find("meta", property="og:image")
    if isinstance(og, Tag):
        content = og.get("content")
        if isinstance(content, str) and validate_url(content):
            return _upgrade_iiif(content)

    # Fallback: first /imgs/ image on the page
    for img in soup.find_all("img", src=True):
        if not isinstance(img, Tag):
            continue
        src = img.get("src")
        if isinstance(src, str) and "/imgs/" in src and validate_url(src):
            return _upgrade_iiif(src)

    return None

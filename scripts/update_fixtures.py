"""Fetch current HTML from the live site and save to tests/fixtures/.

Run this script whenever the Church website structure changes to refresh the
HTML snapshots used by test_scraper.py.

Usage:
    python scripts/update_fixtures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from the repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gencon_audiobook.scraper import (
    _fetch,
    _make_http_session,
    parse_conference_archive,
    parse_conference_listing,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
ARCHIVE_URL = "https://www.churchofjesuschrist.org/study/general-conference"


def main() -> None:
    """Fetch and save the three HTML fixtures needed by test_scraper.py."""
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    http = _make_http_session()

    # 1. Conference archive page
    print(f"Fetching {ARCHIVE_URL} ...")
    archive_html = _fetch(http, ARCHIVE_URL)
    (FIXTURES_DIR / "conference_archive.html").write_text(archive_html, encoding="utf-8")
    print(f"  Saved conference_archive.html ({len(archive_html):,} chars)")

    # Find most recent conference from the archive
    refs = parse_conference_archive(archive_html)
    if not refs:
        print("ERROR: Could not find any conferences in archive page.", file=sys.stderr)
        sys.exit(1)

    most_recent = refs[0]
    print(f"  Most recent: {most_recent.title} -> {most_recent.url}")

    # 2. Conference listing page
    print(f"Fetching {most_recent.url} ...")
    listing_html = _fetch(http, most_recent.url)
    (FIXTURES_DIR / "conference_listing.html").write_text(listing_html, encoding="utf-8")
    print(f"  Saved conference_listing.html ({len(listing_html):,} chars)")

    # Find first talk from the listing
    sessions = parse_conference_listing(listing_html)
    if not sessions or not sessions[0].talks:
        print("ERROR: Could not find any talks in conference listing.", file=sys.stderr)
        sys.exit(1)

    first_talk = sessions[0].talks[0]
    print(f"  First talk: {first_talk.title!r} by {first_talk.speaker!r}")
    print(f"  Talk URL: {first_talk.talk_url}")

    # 3. Individual talk page
    print(f"Fetching {first_talk.talk_url} ...")
    talk_html = _fetch(http, first_talk.talk_url)
    (FIXTURES_DIR / "talk_page.html").write_text(talk_html, encoding="utf-8")
    print(f"  Saved talk_page.html ({len(talk_html):,} chars)")

    print("\nFixtures updated:")
    for f in sorted(FIXTURES_DIR.glob("*.html")):
        print(f"  {f.name}: {f.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()

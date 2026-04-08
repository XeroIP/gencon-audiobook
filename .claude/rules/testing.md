---
globs: tests/**/*.py
---

# Testing Rules

## Naming
- Test functions: `test_<function_name>_<scenario>` (e.g., `test_download_file_retries_on_503`)
- Fixtures in `conftest.py` for anything used by more than one test file

## HTTP mocking
- Never make real HTTP requests in unit tests — use the `responses` library to mock
- Mock at the boundary (`requests.get`, not internal functions)
- Live tests that hit the real site are marked `@pytest.mark.live` and excluded from normal CI

## Assertions
- Assert with descriptive failure messages: `assert result == expected, f"Expected {expected}, got {result}"`
- Test one thing per test function — split large tests into focused cases

## Fixtures
- HTML fixture files live in `tests/fixtures/`
- Audio test fixtures (short silent MP3s) are generated programmatically, not committed
- `scripts/update_fixtures.py` refreshes HTML fixtures from the live site

## Test organization
- `test_scraper.py` — unit tests against saved HTML fixtures
- `test_scraper_live.py` — live smoke tests (`@pytest.mark.live`)
- `test_downloader.py` — mocked HTTP tests
- `test_audio.py` — audio pipeline with generated silent fixtures
- `test_epub.py` — EPUB structure validation
- `test_utils.py` — sanitization and URL validation edge cases
- `test_integration.py` — end-to-end (marked `@pytest.mark.integration`, excluded from normal CI)

## Coverage
- Unit tests must cover: success path, error/retry path, edge cases (empty input, missing fields)
- Integration tests cover the full pipeline from scrape to output files

# Contributing to gencon-audiobook

Thank you for considering a contribution. This project is small and
intentionally simple — please read this before opening a PR.

## Before you start

All changes require a GitHub issue. Open one first so we can discuss the
approach before you invest time writing code. The only exceptions are
cosmetic fixes (typos, whitespace).

## What we need most

- **Website resilience fixes** — the Church website changes structure
  occasionally. If scraping breaks, a fix with updated HTML fixtures is the
  highest-value contribution possible.
- **Bug reports with reproduction steps** — clear reports with the full
  `gencon-audiobook.log` attached are genuinely helpful.
- **Existing-language support** — the code currently handles English only.
  Adding another language with full test coverage would be welcome.

## What we are not looking for right now

- New CLI flags or options without a compelling use case
- Dependency replacements (lxml, ebooklib, etc.) — the current choices are
  intentional; see the [Technical Decisions](https://github.com/XeroIP/gencon-audiobook/wiki/Technical-Decisions) wiki page
- Reformatting or style-only PRs

## Development setup

```bash
git clone https://github.com/XeroIP/gencon-audiobook.git
cd gencon-audiobook
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -e ".[dev]"
```

## Running tests

```bash
# Unit tests (no network, no ffmpeg required)
pytest tests/ --ignore=tests/test_scraper_live.py --ignore=tests/test_integration.py

# Unit tests with coverage report
pytest tests/ --ignore=tests/test_scraper_live.py --ignore=tests/test_integration.py \
    --cov=gencon_audiobook --cov-report=term-missing

# Build source and wheel distributions
python -m build

# Live smoke tests (hits the real website — use sparingly)
pytest tests/test_scraper_live.py -v -m live

# End-to-end integration test (requires ffmpeg on PATH)
pytest tests/test_integration.py -v -m integration
```

All new code must come with tests. See `.claude/rules/testing.md` for
the project's testing conventions.

## When the Church website changes

The scraper depends on the structure of the Church's website. When the site
changes, the HTML fixtures go stale and scraper tests may fail. Here is the
step-by-step process for fixing it:

1. **Refresh the HTML fixtures** from the live site:
   ```bash
   python scripts/update_fixtures.py
   ```
   This fetches the current archive page, most recent conference listing, and
   first talk page, then saves them to `tests/fixtures/`.

2. **Run the scraper unit tests** to see what broke:
   ```bash
   pytest tests/test_scraper.py -v
   ```

3. **Update the CSS selectors and JSON paths** in `src/gencon_audiobook/scraper.py`
   until the tests pass. The scraper uses a dual-strategy approach (JSON primary,
   HTML fallback), so check both.

4. **Run the tests again** to confirm everything passes:
   ```bash
   pytest tests/test_scraper.py -v
   ```

5. **Run the live smoke tests** to verify against the real site:
   ```bash
   pytest tests/test_scraper_live.py -v -m live
   ```

6. **Submit a PR** with updated fixtures and the scraper fix. Reference the
   GitHub issue and explain what changed on the site.

## Code style

- Python 3.10+, type annotations on all public functions
- `from __future__ import annotations` at the top of every module
- Google-style docstrings with `Args`, `Returns`, `Raises` sections
- `logger = logging.getLogger(__name__)` in every module that logs
- No emojis anywhere — not in code, log messages, or output strings
- See `.claude/rules/code-style.md` for the full style guide

## Pull request checklist

- [ ] GitHub issue linked in the PR description (`Closes #N`)
- [ ] Tests added or updated
- [ ] `pytest tests/ --ignore=tests/test_scraper_live.py --ignore=tests/test_integration.py` passes
- [ ] If scraper changed: HTML fixtures updated via `scripts/update_fixtures.py`
- [ ] No new dependencies without discussion in the issue first

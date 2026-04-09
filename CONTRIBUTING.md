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
  intentional; see `docs/spec.md`
- Reformatting or style-only PRs

## Development setup

```bash
git clone https://github.com/XeroIP/gencon-audiobook.git
cd gencon-audiobook
pip install -e ".[dev]"
```

## Running tests

```bash
# Unit tests (no network, no ffmpeg required)
pytest tests/ --ignore=tests/test_scraper_live.py --ignore=tests/test_integration.py

# Live smoke tests (hits the real website — use sparingly)
pytest tests/test_scraper_live.py -v -m live

# End-to-end integration test (requires ffmpeg on PATH)
pytest tests/test_integration.py -v -m integration
```

All new code must come with tests. See `.claude/rules/testing.md` for
the project's testing conventions.

## Code style

- Python 3.10+, type annotations on all public functions
- Google-style docstrings
- No emojis anywhere — not in code, log messages, or output strings
- See `.claude/rules/code-style.md` for the full style guide

## Updating HTML fixtures

If the Church website changes structure, update the saved fixtures before
fixing the scraper:

```bash
python scripts/update_fixtures.py
```

Then fix the scraper and verify `pytest tests/test_scraper.py` passes.

## Pull request checklist

- [ ] GitHub issue linked in the PR description (`Closes #N`)
- [ ] Tests added or updated
- [ ] `pytest tests/ --ignore=tests/test_scraper_live.py --ignore=tests/test_integration.py` passes
- [ ] No new dependencies without discussion in the issue first

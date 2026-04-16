# gencon-audiobook

Python CLI tool that downloads General Conference talks from churchofjesuschrist.org and produces
an m4b audiobook with chapters and an epub companion with full transcripts. Cross-platform,
single `pip install`, no user prerequisites beyond Python 3.10+.

## Tone
Be brutally honest and direct. If a design choice is bad, say so and explain why. If code quality
is lacking, flag it immediately. Do not sugarcoat feedback. This project serves a community and
must be high quality. Problems caught early are cheap; problems caught late are expensive.

## Build and Test Commands
```bash
pip install -e ".[dev]"                                          # install with dev dependencies
pytest tests/ -v --ignore=tests/test_scraper_live.py \
              --ignore=tests/test_integration.py                 # unit tests only
pytest tests/test_scraper_live.py -v -m live                     # live site smoke test
pytest tests/test_integration.py -v -m integration               # end-to-end test
pytest --cov=gencon_audiobook --cov-report=term-missing          # coverage report
python -m build                                                   # build package
gencon-audiobook --help                                           # CLI help
```

## Code Standards
See `.claude/rules/code-style.md` for Python style, logging, and comment conventions.
See `.claude/rules/testing.md` for test naming, mocking, and fixture conventions.
See `.claude/rules/security.md` for URL validation, filename sanitization, and SSL rules.
See `.claude/rules/epub-style.md` for EPUB CSS and structure rules.

## Key Technical Decisions
See `docs/spec.md` for the full specification. Critical points:
- HTML parsing: `html.parser` (stdlib) — NOT lxml
- EPUB generation: manual ZIP of XHTML — NOT ebooklib
- m4b chapters: ffmpeg FFMETADATA1 format — mutagen is for verification only, NOT writing
- Conference scope: scrape ALL available conferences; user selects
- ffmpeg: check system PATH first, then static-ffmpeg fallback
- CLI flags: `--audiobook-only` / `--epub-only` / `--force-scrape`
- Conference metadata cached in `conference.json` after first scrape; `cache.py` handles serialize/deserialize
- Image downloads parallelized via `ThreadPoolExecutor` (8 workers, thread-local sessions); audio sequential

## Copyright
Downloaded content is copyright Intellectual Reserve, Inc. Tool code is MIT licensed.
Always embed copyright notices in output files (m4b comment metadata, epub copyright page).
Never include content copyright under the MIT license.

## Output Style
No emojis anywhere — not in terminal output, log messages, generated files, or documentation.

## GitHub Issues
All changes require a GitHub issue before work begins. Cosmetic fixes (typos, whitespace) are
the only exception. Use `gh issue create` following the project's issue format.

Every PR description body must include `Closes #N` for each issue it resolves. GitHub reads
the PR body (not the commit message) to auto-close issues on squash merge — omitting it leaves
issues open after the PR lands.

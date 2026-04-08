# Phase 4: Packaging and CI/CD

## Objective

Make the project publishable to PyPI, tested across all target platforms and Python versions,
with automated detection of website changes.

Refer to `docs/spec.md` and `.claude/rules/`.

---

## Prerequisites

- Phase 3 complete: full CLI with error handling and logging
- All unit tests pass
- `python -m build` succeeds locally

---

## Step 1: GitHub Actions — `test.yml`

Run the full test suite on every push and pull request.

```yaml
# .github/workflows/test.yml
name: Tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
        python-version: ["3.10", "3.11", "3.12", "3.13"]

    runs-on: ${{ matrix.os }}

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install dependencies
        run: pip install -e ".[dev]"
      - name: Run tests
        run: pytest tests/ -v --ignore=tests/test_scraper_live.py --ignore=tests/test_integration.py
      - name: Run pip-audit
        run: pip-audit
```

---

## Step 2: GitHub Actions — `publish.yml`

Publish to PyPI when a release tag is created. Uses trusted publishing (no tokens in secrets).

```yaml
# .github/workflows/publish.yml
name: Publish to PyPI

on:
  release:
    types: [published]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Build package
        run: |
          pip install build
          python -m build
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/

  publish:
    needs: build
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - uses: pypa/gh-action-pypi-publish@release/v1
```

Note: Configure PyPI trusted publishing in the PyPI project settings before first release.
Add documentation in `CONTRIBUTING.md` for how to do this.

---

## Step 3: GitHub Actions — `live-test.yml`

Weekly cron job that runs the live scraper smoke test. Opens a GitHub issue automatically
on failure, so website changes are caught before users report them.

```yaml
# .github/workflows/live-test.yml
name: Live Site Smoke Test

on:
  schedule:
    - cron: "0 9 * * 1"  # Every Monday at 9 AM UTC
  workflow_dispatch:       # Also triggerable manually

jobs:
  live-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: pip install -e ".[dev]"
      - name: Run live smoke test
        id: live_test
        run: pytest tests/test_scraper_live.py -v -m live
        continue-on-error: true
      - name: Open GitHub issue on failure
        if: steps.live_test.outcome == 'failure'
        uses: actions/github-script@v7
        with:
          script: |
            const title = 'Automated: live site smoke test failed';
            const body = `The weekly live site smoke test failed.

            This usually means the Church website structure has changed.

            **Next steps:**
            1. Run \`python scripts/update_fixtures.py\` to fetch current HTML
            2. Compare the new fixtures to the old ones to identify what changed
            3. Update the CSS selectors in \`scraper.py\` to match the new structure
            4. Update tests and fixtures
            5. Open a PR with the fix

            Workflow run: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}`;

            // Check if an issue is already open for this
            const issues = await github.rest.issues.listForRepo({
              owner: context.repo.owner,
              repo: context.repo.repo,
              state: 'open',
              labels: 'website-changed',
            });

            if (issues.data.length === 0) {
              await github.rest.issues.create({
                owner: context.repo.owner,
                repo: context.repo.repo,
                title: title,
                body: body,
                labels: ['bug', 'website-changed'],
              });
            }
```

---

## Step 4: Repository Setup (One-Time)

Before the CI workflows will work correctly, create the required GitHub label:

```bash
gh label create website-changed --description "The Church website structure changed" --color "e4e669"
```

The `live-test.yml` workflow filters for open issues with this label before creating a new one.
If the label does not exist, the issue-creation API call will fail silently.

---

## Step 5: Issue Templates

### `.github/ISSUE_TEMPLATE/bug_report.md`

```markdown
---
name: Bug report
about: Something is broken
labels: bug
---

## Description
<!-- What went wrong? -->

## Steps to reproduce
1.
2.
3.

## Expected behavior
<!-- What should have happened? -->

## Actual behavior
<!-- What happened instead? -->

## Environment
- OS:
- Python version (`python --version`):
- Tool version (`gencon-audiobook --version`):

## Log output
<!-- Paste the relevant section of gencon-audiobook.log -->
<!-- The log is in your output directory (default: ~/gencon-audiobook/) -->
```

### `.github/ISSUE_TEMPLATE/website_changed.md`

```markdown
---
name: Website structure changed
about: The Church website changed and the tool is broken
labels: bug, website-changed
---

## What happened
<!-- What error did you see? -->

## Tool output
<!-- Paste the terminal output -->

## Log output
<!-- Paste from gencon-audiobook.log — look for WARNING or ERROR lines -->

## Environment
- OS:
- Python version:
- Tool version:
- Date the tool last worked (if known):
```

---

## Step 6: `CONTRIBUTING.md`

Must cover:

1. **Development setup**
   ```bash
   git clone https://github.com/XeroIP/gencon-audiobook
   cd gencon-audiobook
   pip install -e ".[dev]"
   pytest tests/ -v --ignore=tests/test_scraper_live.py --ignore=tests/test_integration.py
   ```

2. **Running the full test suite**
   - Unit tests: pytest command (exclude live and integration)
   - Live test: how to run and what it does
   - Integration test: how to run and what it does
   - Coverage: pytest --cov command

3. **When the website changes** (most common contribution)
   - Step-by-step: run `update_fixtures.py`, compare old/new HTML, update selectors, update tests
   - How to identify which selector broke (reading the log)
   - PR requirements: fixtures updated, all unit tests pass

4. **Adding a new feature**
   - Open a GitHub issue first
   - Follow code standards in `.claude/rules/code-style.md`
   - Tests required for all new code
   - PR must include: issue reference, test coverage, updated documentation if needed

5. **Publishing a release** (maintainer-only)
   - Update version in `src/gencon_audiobook/__init__.py` and `pyproject.toml`
   - Create a GitHub release with a tag — `publish.yml` handles the rest
   - First release: set up PyPI trusted publishing beforehand

---

## Phase 4 Test Plan

```bash
# 1. Build package locally
pip install build
python -m build
# Expected: dist/ contains .whl and .tar.gz

# 2. Install from wheel and verify
pip install dist/gencon_audiobook-*.whl
gencon-audiobook --version
gencon-audiobook --help

# 3. Test install from test PyPI
# (Do this before first real release)
# Upload to test.pypi.org first:
# pip install twine && twine upload --repository testpypi dist/*
# Then install from test PyPI:
# pip install --index-url https://test.pypi.org/simple/ gencon-audiobook

# 4. Verify CI passes
# Push to GitHub, check Actions tab:
# - test.yml: all 12 matrix entries (3 OS x 4 Python versions) pass
# - pip-audit: no vulnerabilities reported

# 5. Trigger live test manually
# GitHub Actions -> "Live Site Smoke Test" -> "Run workflow"
# Expected: passes

# 6. Verify issue template format
# GitHub -> Issues -> "New Issue" -> verify templates appear

# 7. Verify website-changed label exists
gh label list | grep website-changed
# Expected: label is present
```

**Exit criteria**: CI green on all 12 matrix entries. Package builds and installs cleanly.
PyPI publish workflow works against test.pypi.org.

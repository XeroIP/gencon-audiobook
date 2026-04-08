---
globs: src/**/*.py
---

# Security Rules

## URL validation
- Validate ALL URLs against the domain allowlist before fetching:
  - `churchofjesuschrist.org`
  - `*.ldscdn.org`
  - `media*.churchofjesuschrist.org`
- Reject and log any URL outside the allowlist — never silently skip
- MP3 URLs must match `https://*.ldscdn.org/*.mp3` or `https://media*.churchofjesuschrist.org/*`
- Log all external URLs fetched at DEBUG level

## Filename sanitization
- Strip/replace all characters outside `[a-zA-Z0-9 ._-]`
- Prevent path traversal: reject `..`, absolute paths, and null bytes
- Truncate filenames exceeding 200 characters

## SSL / TLS
- Never set `verify=False` on any HTTP request
- Never disable certificate verification for any reason

## Code execution
- Never `eval()` or `exec()` scraped content
- The Church site embeds base64-encoded JSON in page state — decode and `json.loads()` only, never execute

## HTTP timeouts
- Always set explicit timeouts on every `requests` call
- HTML pages: connect=15s, read=30s
- MP3 downloads: connect=30s, read=120s
- No request without a timeout — no infinite hangs

## Credentials
- No API keys, tokens, or credentials anywhere in the codebase
- All content scraped is publicly accessible without authentication

## User-Agent
- Identify as `gencon-audiobook/<version> (open source; github.com/XeroIP/gencon-audiobook)`
- Never impersonate a browser

## Dependencies
- Major versions pinned in `pyproject.toml`
- `pip-audit` runs in CI on every push

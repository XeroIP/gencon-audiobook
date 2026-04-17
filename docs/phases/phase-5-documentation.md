# Phase 5: Documentation

## Objective

Write the README and legal documentation needed for v1 launch. This is the public-facing
documentation that users and contributors will see first.

Refer to `docs/spec.md` for accurate technical details and platform notes.

---

## Prerequisites

- Phases 1-4 complete: tool works, CI passes, package builds
- All technical decisions finalized (so documentation reflects actual behavior)

---

## Step 1: `README.md`

The README is the first thing users and potential contributors see. Write it for two audiences:
a non-technical user who wants to listen to General Conference, and a developer who wants to
contribute.

### Required sections, in order:

1. **Project title and one-line description**

2. **Disclaimer** (prominent, near the top)
   ```
   Disclaimer: This is an unofficial tool not affiliated with The Church of Jesus Christ of
   Latter-day Saints. General Conference content is copyright Intellectual Reserve, Inc.
   All rights reserved. This tool downloads content for personal, noncommercial use as
   permitted by the Church's Terms of Use. Please respect the Church's intellectual property.
   ```

3. **What it does** — 2-3 sentences. Plain English.

4. **Requirements**
   - Python 3.10 or newer
   - Approximately 500 MB of disk space per conference
   - Internet connection
   - ffmpeg (automatically downloaded if not already installed)

5. **Installation**
   ```bash
   pip install gencon-audiobook
   ```

6. **Usage**
   ```bash
   gencon-audiobook                               # Most recent conference
   gencon-audiobook --conference 2024-04          # Specific conference
   gencon-audiobook --audiobook-only              # m4b only
   gencon-audiobook --epub-only                   # epub only
   gencon-audiobook --output ~/Books              # Custom output directory
   gencon-audiobook --verbose                     # Show detailed output
   gencon-audiobook --help                        # All options
   ```

7. **Output**
   Show the directory structure produced (from `docs/spec.md`).

8. **Using your files**

   **Audiobook (.m4b):**
   - iPhone/iPad: Apple Books, BookPlayer, or Bound (native support, chapters work)
   - Android: Requires a dedicated audiobook app. **Smart AudioBook Player** (free on Play
     Store) is recommended. The default music app and Google Play Books do NOT support m4b files.
   - Mac: Apple Books or iTunes
   - Windows: iTunes (for chapters) or VLC (audio only, chapters not shown)

   **Ebook (.epub):**
   - iPhone/iPad: Apple Books (just tap the file)
   - Android: Google Play Books (built in), Moon+ Reader, or ReadEra
   - Kindle: Use "Send to Kindle" — Amazon automatically converts epub
   - Computer: Calibre (free, recommended) or any epub reader

9. **Updating**
   ```bash
   pip install --upgrade gencon-audiobook
   ```

10. **Troubleshooting**

    | Problem | Solution |
    |---|---|
    | "command not found: gencon-audiobook" | Python scripts directory is not on PATH. See [Python PATH guide](https://docs.python.org/3/using/cmdline.html) |
    | "Could not connect" | Check your internet connection |
    | Audiobook has no chapters | Use an audiobook-specific player. Smart AudioBook Player for Android, Apple Books for iOS. |
    | Tool stopped working after a site update | [Open a GitHub issue](https://github.com/XeroIP/gencon-audiobook/issues/new/choose) — it will be fixed |
    | Error with log details | Paste the log from `~/gencon-audiobook/<conference>/gencon-audiobook.log` in your issue |

11. **Credits**
    Inspired by [ChurchofJesusChristDev/General-Conference-to-Audiobook](https://github.com/ChurchofJesusChristDev/General-Conference-to-Audiobook).

12. **Contributing**
    See [CONTRIBUTING.md](CONTRIBUTING.md).

13. **License**
    Tool code: MIT. Downloaded content: copyright Intellectual Reserve, Inc. See [LICENSE-CONTENT.md](LICENSE-CONTENT.md).

### Style rules for README

- No emojis
- Use plain, direct language — assume the reader is not a developer
- Every code block must be copy-paste ready (no placeholders like `<your-path>`)
- Platform instructions must be specific: app names, not "use an app that supports this format"

---

## Step 2: `LICENSE-CONTENT.md`

```markdown
# Content Copyright Notice

General Conference audio recordings, transcripts, and images downloaded by this tool are
copyright Intellectual Reserve, Inc. All rights reserved.

This tool is designed for personal, noncommercial use, which is permitted under the Terms of
Use of The Church of Jesus Christ of Latter-day Saints
(https://www.churchofjesuschrist.org/legal/terms-of-use).

The MIT license in the LICENSE file applies ONLY to the source code of this tool.
It does NOT apply to any content downloaded by this tool.

Downloaded content may not be:
- Redistributed or shared publicly
- Used for commercial purposes
- Modified and republished

For questions about permitted uses of General Conference content, refer to the Church's
Terms of Use or contact the Church directly.
```

---

## Step 3: `LICENSE`

Standard MIT license. Replace `[year]` with the actual year and `[fullname]` with `XeroIP`.

---

## Post-v1 Documentation Roadmap

The following documentation is NOT part of this phase. Add after the tool is proven in use
and you understand what users actually struggle with.

- **`docs/user-guide.md`** — ELI5 install and usage for Windows/macOS/Linux, with screenshots
- **`docs/listening-guide.md`** — Device-specific guide for opening and using the downloaded files
- **`docs/technical-decisions.md`** — Every technical decision with rationale (see `docs/spec.md`
  as the source of truth — this doc would expand each decision with fuller context)
- **`docs/architecture.md`** — Data flow diagrams, module responsibilities, extensibility points

---

## Phase 5 Test Plan

```bash
# 1. README review
# Read README.md aloud from start to finish.
# Check: would a non-technical person understand every step?
# Check: are all commands copy-paste ready?
# Check: are platform-specific instructions accurate and specific?
# Check: no emojis anywhere

# 2. Follow your own README
# On a clean machine with only Python installed:
# - Follow the Installation section exactly
# - Run gencon-audiobook
# - Open the output files using the instructions in "Using your files"
# - Every step should work without needing external help

# 3. LICENSE-CONTENT.md review
# Check: clearly distinguishes tool license from content copyright
# Check: mentions personal, noncommercial use
# Check: does NOT claim MIT license covers downloaded content

# 4. Troubleshooting table
# Verify each row is accurate for the current version of the tool

# 5. Credits link
# Verify the link to the original project works
```

**Exit criteria**: README is accurate, complete, and followable by a non-technical user.
LICENSE-CONTENT.md clearly and accurately describes the content copyright situation.

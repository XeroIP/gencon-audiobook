# GitHub Issue Format

When asked to create a GitHub issue, use `gh issue create` with the format below.
Choose the template that matches the issue type. Fill every section — never leave
a section empty or with placeholder text.

---

## Issue types and title prefixes

| Type | Title prefix | Label |
|---|---|---|
| Bug (user-visible breakage) | `bug: ` | `bug` |
| Fix (code correctness, not user-visible) | `fix: ` | `bug` |
| Feature / enhancement | `feat: ` | `enhancement` |
| Test coverage gap | `test: ` | `test` |
| Documentation drift | `docs: ` | `documentation` |
| Maintenance / chore | `chore: ` | `chore` |
| Security | `security: ` | `security` |

---

## Bug / fix template

```
gh issue create \
  --title "bug: <short description>" \
  --label "bug" \
  --body "## Problem

<What is broken. One paragraph. State the symptom and when it occurs.>

## Where

- \`src/gencon_audiobook/<file>.py\` line N: <what the bad code does>

## Expected behavior

<What should happen instead.>

## Steps to reproduce

1. <step>
2. <step>

## Fix

<Proposed fix, or 'Unknown — needs investigation' if not yet known.>"
```

---

## Feature / enhancement template

```
gh issue create \
  --title "feat: <short description>" \
  --label "enhancement" \
  --body "## Problem / motivation

<Why this feature is needed. What user problem does it solve?>

## Proposed solution

<What the feature should do. Be specific about behavior, not implementation.>

## Scope

**In scope:**
- <item>

**Out of scope:**
- <item>

## Open questions

- <Any design decisions that need discussion before implementation.>"
```

---

## Test coverage gap template

```
gh issue create \
  --title "test: <short description>" \
  --label "test" \
  --body "## Gap

<What scenario, path, or behavior is not tested.>

## Where

- \`tests/<file>.py\`: <what is missing>

## Why it matters

<What kind of bug would slip through without this test.>

## Suggested test

\`\`\`python
def test_<function>_<scenario>():
    # <sketch of what the test should do>
\`\`\`"
```

---

## Documentation template

```
gh issue create \
  --title "docs: <short description>" \
  --label "documentation" \
  --body "## Problem

<What is wrong or missing in the documentation.>

## Where

- \`<file>\` line N: <what it says vs. what it should say>

## Fix

<What the correct content should be.>"
```

---

## Chore / maintenance template

```
gh issue create \
  --title "chore: <short description>" \
  --label "chore" \
  --body "## What

<What needs to be done. Be specific about the change.>

## Why

<Why this maintenance work matters now.>

## Acceptance criteria

- [ ] <measurable outcome>
- [ ] <measurable outcome>"
```

---

## Rules

- **One issue per logical change.** Do not bundle unrelated work into one issue.
- **Always include `Closes #N` in the PR description body** (not the commit message)
  when a PR resolves an issue. GitHub reads the PR body to auto-close issues on merge.
- **Cosmetic fixes** (typos, whitespace) are the only exception to the "issue first" rule.
- **Do not create duplicate issues.** Search open issues before creating a new one.
- **Labels must match the title prefix.** If the label does not exist, create it with
  `gh label create`.

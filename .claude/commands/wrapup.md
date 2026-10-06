---
description: Write a handoff to STATUS.md for the next session, then commit it
---
Write a handoff in STATUS.md so the next session can pick up cold, without this conversation.

1. Review this session: what changed, what is half-done or broken, and anything learned that isn't obvious from the code.
2. Get the current time: run `date +%Y-%m-%dT%H:%M:%S%:z` (or `Get-Date -Format o` in PowerShell).
3. Rewrite STATUS.md, keeping its front matter and section headings:
   - `updated`: the timestamp from step 2. `source`: manual.
   - `state` and `priority`: keep unless this session changed them. Use `blocked` if work can't continue without something external.
   - Done recently: replace rather than accumulate; keep the last few meaningful items.
   - Next step: one concrete action someone could start on immediately (a file, function, or command), never "continue working on X".
   - Blockers / waiting on: decisions or information needed from me, and external dependencies.
   - Keep the whole file under about 40 lines.
   - Nothing sensitive: no credentials, tokens, IP addresses, hostnames, internal URLs, or personal details. Describe them generically. This file is committed and may be public.
4. Commit STATUS.md. If there are other uncommitted changes, ask me whether to include them, commit them as WIP, or leave them.
5. Push if the branch has an upstream or this is a cloud session.

Extra notes from me, if any: $ARGUMENTS

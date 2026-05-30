# Cursor Rules for GcodeSetup

## Core Rule

Make small targeted changes only.

Do not rewrite the whole app.

Do not refactor large sections unless specifically asked.

Do not change parser logic unless the user specifically asks.

Do not change UI/layout unless the user specifically asks.

Do not change setup sheet layout unless the user specifically asks.

Always preserve existing working formats.

## Before Editing

Before making any code change:

1. Read AI_CONTEXT.md.
2. Read TEST_CASES.md if the task affects parser or detection.
3. Identify the exact file and function that need changes.
4. Explain briefly what will be changed.
5. Make the smallest possible edit.

## Parser Rules

When updating parser or detection:

- Do not break existing supported formats.
- Do not mix unrelated format rules together unnecessarily.
- Prefer profile-style handlers for special formats.
- Keep universal output fields consistent.
- Preserve program sequence by default.
- Do not auto-sort unless user presses sort.
- Do not invent missing N sequence numbers.
- Do not use machine transform commands as operation comments.
- Do not treat comments as axis motion.
- Strip comments before checking real axis movement.
- Add new detection rules carefully and avoid false positives.

## UI Rules

When updating UI:

- Keep the app simple and professional.
- Do not add login, payment, subscription, or database unless specifically requested.
- Do not remove existing beta safety/privacy notes.
- Do not expose admin diagnostic data without password lock.
- Keep setup sheet printable and compact.
- Keep operation rows editable.

## Testing Rules

After any parser or detection change, test at least:

1. The new sample related to the change.
2. One existing milling sample.
3. One existing Siemens/DMG sample if the change touches 5-axis detection.
4. One existing lathe/mill-turn sample if the change touches lathe detection.

Update CHANGELOG_AI.md after completing the change.

## Response Rule

After editing, summarize:

- Files changed
- What changed
- What was intentionally not changed
- What to test next

Do not claim success unless the change was actually made.

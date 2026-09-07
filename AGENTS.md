# Agent notes

Skills live in `skills/`, one directory each with a `SKILL.md`. Read the one
that matches the task before acting:

- `skills/xte-push/` — put text, a price label, a QR code or an image on the
  e-paper shelf tag. One command, no protocol knowledge needed.

Claude Code finds them through the symlinks in `.claude/skills/`. Codex and
other agents: read this file, then the relevant `SKILL.md`.

Conventions: run Python through `.venv/bin/python` from the repo root; the
protocol reference is `docs/protocol.md`; every codec port must pass
`testdata/reference.json`. Do not touch `hardware/` or `references/` for a
display update.

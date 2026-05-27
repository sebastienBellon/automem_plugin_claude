# Changelog

## v0.4.0 — 2026-05-27 — Non-destructive recall affordances

**Theme.** Address the namespace fragmentation discovered between
auto-derived owner-repo slugs (Claude Code hook) and human slugs (Claude.ai
chat / Cowork conventions) **without** introducing any new classification
axis at store time. The earlier v0.4.0 spec considered adding a `realm:`
tag and splitting storage into two regimes (code vs life), but was pivoted
to a minimalist version after surfacing that any tagging-discipline system
eventually degrades silently (cf. Obsidian-style tagging experience) and
adds noise that complicates retrieval evals.

The two additions in this release are both **purely additive metadata** —
deterministic, never invented by the agent, never modifying existing
memories. The bigger architectural questions (`realm:`, regime split,
dropping `project:` for life contexts) are deferred until empirical recall
quality data justifies them.

### Added

- **Dual-tag mechanism via project_map.json alias** (`scripts/_project.py`).
  Entries in `~/.automem-plugin/project_map.json` can now be either the
  legacy string form `{cwd: "owner-repo"}` (still supported) or a v0.4.0
  object form `{cwd: {"slug": "owner-repo", "alias": "human-name"}}`.
  When an alias is configured, the hook injects BOTH `project:owner-repo`
  AND `project:human-name` into every `store_memory` call's tags. Recall
  on either tag finds the memory — fixing the historical case where a
  store from Claude Code on `whisperithq/monorepo` landed under
  `project:whisperithq-monorepo` and a store from Claude.ai chat landed
  under `project:whisperit`, and recall on one missed the other.
- **`AUTOMEM_PROJECT_ALIAS` env var** exported by `scripts/_project.sh`
  alongside `AUTOMEM_PROJECT_ID`. Hooks consume it to build dual-tag
  fragments.
- **Auto-injected `period:` tags** in `on_stop.sh` and `on_pre_compact.sh`
  rubrics. Every store-memory template now includes
  `period:YYYY-MM-DD` and `period:YYYY-Www` (ISO week) computed at
  rubric-emission time via bash `date +%Y-%m-%d` and `date +%G-W%V`.
  Enables cheap temporal recall (`tag_match=prefix` on `period:2026-05`,
  exact match on `period:2026-05-27`, etc.) without any new skill or
  agent heuristic. Deterministic metadata, never wrong.
- **`/automem:switch-project --alias <human-slug>`** — new subcommand
  that writes the alias for the current cwd into `project_map.json` via
  the new `_project.save_alias()` helper. Upgrades a legacy string entry
  to the object form, or creates a fresh object entry if none existed.
  Also `--alias-remove` to collapse back to legacy string form.
- **`resolve_alias(cwd)` and `save_alias(cwd, alias)`** Python helpers
  in `scripts/_project.py`. Exposed for use by skills and external
  tooling.
- **SessionStart banner alias awareness** — when an alias is configured,
  the rubric explicitly tells Claude to dual-tag every store.

### Changed

- **`scripts/_project.sh`** rewritten to invoke python3 once (returning
  a JSON blob) instead of three separate fork+import cycles, cheaper at
  hook firing time and surfaces alias + branch + project_id atomically.
- **`save_project_mapping()`** now preserves an existing alias when the
  slug is updated (previously a slug update would strip the alias field).

### Backward compatibility

- All existing `project_map.json` files keep working as-is. Legacy
  string-only entries (`{cwd: "slug"}`) continue to resolve correctly,
  the `alias` field defaults to empty string, and no dual-tag is emitted.
- The `t_invalid`, period, and alias additions are purely additive — no
  existing memory is touched.

### Deferred (intentionally)

- `realm:` tag axis (work/personal). Deferred until empirical recall
  failures justify it; see memory `7af835d8-918d-44a1-baf7-cb3e54b1580d`
  for the design discussion that landed on the minimalist version.
- Regime split (drop `project:` for non-code stores). Same reasoning.
- `/automem:journal` and `/automem:open-threads` skills. Either won't be
  needed (temporal recall is handled by `period:` tags + the existing
  `time_query` parameter of `recall_memory`) or carry KPMS-drift risk
  for retrieval evals.

### Validation

Six scenarios tested in isolation against `_project.py`:
- empty `project_map.json` → falls through cascade to `"default"`
- legacy string entry → slug only, empty alias
- object entry with alias → both resolve correctly
- object entry without alias → slug only, empty alias
- `save_alias()` upgrades a legacy string entry to object form
- `save_alias("")` collapses object back to legacy string form

All hook rubrics rebuilt and verified to emit the correct tag fragments
with and without alias.

---

## v0.3.3 and earlier

See `git log` for the full history. Highlights:

- **v0.3.3** — soft project tag with empty-result fallback in recall.
- **v0.3.2** — fix project resolution in git worktrees (Conductor, `claude -w`).
- **v0.3.1** — close §9 open design decisions.
- **v0.3.0** — Tier 3 complete (tour, stats, memory-reviewer, context-loader).
- **v0.2.1** — agent-driven memory ops, silent OS layer positioning.
- **v0.2.0** — Tier 2 graph-skills (list-projects + weave); plugin feature-complete.
- **v0.1.x** — initial MVP through Tier 1 graph-skills.

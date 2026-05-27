# Changelog

## v0.4.2 — 2026-05-27 — Nuance: `start`/`end` is a SOFT filter, not hard

**Theme.** Documentation correction following a second live test pass that
revealed `start`/`end` ISO 8601 is not the hard temporal filter v0.4.1 made
it out to be. It's a soft boost the semantic scorer can override when the
query is rich, returning out-of-window matches alongside in-window ones.

The only surgical-grade temporal filter on AutoMem is the `period:` tag
(exact or prefix). v0.4.0 already shipped the correct primitive — this
release just clarifies the documentation so neither agent nor user expect
hard filtering from `start`/`end`.

### Changed

- **`skills/recall/SKILL.md`** — "Temporal queries" section reworked from
  "server quirk" (singular) to "server quirks" (plural). Documents both
  quirks: `time_query` NL parser partial, and `start`/`end` as a soft
  boost. Case A / B / C routing now annotated with reliability tiers:
  Tier 1 (surgical, period: tags, v0.4.0+ memories) vs Tier 2 (soft
  fallback, start/end ISO, covers legacy but loose under rich queries).
  Adds a "Why this matters for the OS-layer promise" closing note: the
  system gets sharper naturally as the memory base accumulates v0.4.0+
  stores.

### Validation

Test 3 of the live verification run (27 May 2026):
- Query "qu'est-ce que j'ai fait hier" + `start="2026-05-26T00:00:00Z"` +
  `end="2026-05-26T23:59:59Z"` → 20 results, many pre-26-May (out of
  window). Previous run with simple query "activité" + same `start`/`end`
  → 2 results in-window. Conclusion: filter is soft, semantic scoring
  wins when query is rich.

Memory `2bab9557-0336-461d-901f-116c7843611f` captures the finding.

---

## v0.4.1 — 2026-05-27 — Document `time_query` server quirk

**Theme.** Documentation-only release that captures an empirically validated
quirk of AutoMem's server-side `time_query` natural-language parser: it
handles `"today"` correctly but silently ignores `"yesterday"`, `"last 24 hours"`,
and presumably other variants — the temporal filter disappears and the call
becomes a pure semantic search, returning out-of-window results ranked by score.

The fix routes around the quirk inside the skills that perform recall, so
agent and user behaviour produces correct temporal filtering by default.

### Changed

- **`skills/recall/SKILL.md`** — `--time-window` flag reworked to refuse raw
  natural-language values; instead accepts `today` (the only working NL value),
  `YYYY-MM-DD` (exact date, expanded to `start`/`end`), `YYYY-MM-DD:YYYY-MM-DD`
  (date range), `YYYY-MM` (whole month, expanded to `period:` prefix match),
  and `YYYY-Www` (ISO week). A new "Temporal queries — server quirk to know"
  section documents the three temporal cases (today / past specific date /
  multi-day range) with concrete recall_memory snippets for each.
- **`skills/context-loader/SKILL.md`** — new edge case "Topic with a temporal
  qualifier" instructs the skill never to pass `time_query="<NL>"` for past
  periods; routes to `start`/`end` ISO or `period:` tag prefix matching
  instead. References the `/automem:recall` skill for the full routing.

### Why not fix upstream

The quirk lives in AutoMem's server-side recall_memory implementation
(FalkorDB+Qdrant adapter). Fixing it there is out of scope for this plugin
release — the plugin can only route around it. The documentation captured
here also serves as a discoverable record if/when the server is patched
later.

### Validation

Empirical tests run in a live conversation on 27 May 2026:
- `time_query="today"` → 9 in-window results (correct).
- `time_query="yesterday"` → 10 out-of-window results, scoring purely semantic (broken).
- `start="2026-05-26T00:00:00Z"` + `end="2026-05-26T23:59:59Z"` → 2 in-window
  results (correct, confirms DB has yesterday's data — the quirk is in the
  parser, not absence of data).
- `tags=["period:2026-05-27"]` exact match → 1 result, the only memory carrying
  that tag (correct, dual-tag mechanism functional).

Memory `1724ca5b-5d86-4b08-8c5f-6b14d39d1476` captures the empirical finding.

---

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

# Plan de portage AutoMem — Plugin Claude Code / Cowork

> Version 2 du plan, **révisée le 26 mai 2026** après inspection des vrais schémas MCP d'AutoMem. La V1 supposait à tort qu'AutoMem clonait la surface mem0 — elle est obsolète.
>
> Le document de référence de la V1 reste disponible dans le scratchpad sous `automem-portage-plan.md` mais ne doit plus servir de guide d'implémentation.

---

## 0. Ce qui a changé entre V1 et V2

Trois découvertes majeures de la session du 25 mai 2026 :

1. **AutoMem n'est pas un clone mem0.** Stack FalkorDB + Qdrant, surface MCP `store_memory` / `recall_memory` / `associate_memories` / `check_database_health`. Pas de `user_id`/`agent_id`/`app_id`/`run_id` natifs.
2. **Les trois "gaps" identifiés en V1 sont invalidés.** `update_memory` accepte content + tags + metadata + importance, `t_valid`/`t_invalid` sont natifs, et `recall_memory` a `sort`/`context_*`/`priority_ids`.
3. **AutoMem a des features uniques** absentes de mem0 et qui méritent d'être au cœur du plugin : `associate_memories` avec 11 types d'arêtes typées, `expand_relations` / `expand_entities` dans `recall_memory`, boost contextuel natif via `active_path` / `language` / `context_tags`.

Conséquence : le plan d'implémentation est **plus simple côté gaps** (rien à émuler pour pin/expiration/threshold) et **plus ambitieux côté features** (le plugin doit exploiter le graphe natif, pas l'ignorer).

---

## 0bis. Contrainte clé : **AutoMem est MCP-only** (pas de REST exposé)

Décision figée le 26 mai 2026 après confirmation utilisateur : l'instance AutoMem auto-hébergée n'expose **que la couche MCP**, pas d'API REST publique. Conséquences architecturales sur tout le plugin :

1. **Aucun hook ne peut faire d'appel direct au serveur AutoMem.** Les scripts bash des hooks n'ont pas accès aux MCP tools (qui ne sont disponibles qu'à Claude lui-même). Donc oubli total des wrappers `_recall.py` / `_store.py` / `capture_compact_summary.py` qu'on aurait pu copier de mem0.
2. **Tout passe par injection de rubriques.** Chaque hook écrit sur stdout une instruction texte que Claude lit puis exécute via les MCP tools. C'est le pattern central déjà identifié, ici poussé jusqu'à 100 %.
3. **Le `memory_count` dans la bannière SessionStart restera `?`** par défaut — Claude le récupère via `check_database_health` à la première opportunité si nécessaire. Pas critique.
4. **`PreCompact` devient critique** pour la persistance entre sessions. C'est le dernier moment où Claude est encore actif et peut appeler `store_memory` avant que le contexte soit compacté/perdu. Pas de filet de sécurité post-compaction (au contraire de mem0 où `capture_compact_summary.py` peut écrire en background via REST).
5. **Avantage** : zéro config utilisateur (pas de `rest_base_url`/`rest_auth_header`), zéro découplage à maintenir, zéro problème d'auth REST.

Ces décisions sont gravées dans `scripts/on_session_start.sh` (count = `?`) et dans toutes les rubriques.

---

## 1. Surface MCP cible — rappel

### 1.1 Tools AutoMem disponibles

| Tool | Signature essentielle | Usage dans le plugin |
|---|---|---|
| `store_memory` | `content, type, tags[], importance, confidence, t_valid, t_invalid, metadata, timestamp, id, embedding[]` | Tous les save : skill remember, hooks Stop / TaskCompleted / PreCompact, auto-import |
| `recall_memory` | `query, queries[], auto_decompose, tags, tag_mode, tag_match, time_query, start, end, context, context_tags[], context_types[], active_path, language, expand_relations, expand_entities, sort, limit, format, priority_ids[]` | Tous les load : skill recall/peek, context-loader, on_file_read, on_user_prompt (resume), on_bash_output (errors) |
| `associate_memories` | `memory1_id, memory2_id, type, strength` (11 types d'arêtes) | Skill associate (explicite), weave (auto-tissage), evolve (remplacement) |
| `update_memory` | `memory_id, content?, type?, tags?, metadata?, importance?, confidence?, timestamps?` | Skill pin (set importance=1, tag pinned), skill remember --update |
| `delete_memory` | `memory_id` | Skill forget |
| `check_database_health` | — | Skill health (1 appel suffit) |

### 1.2 Types fixes AutoMem (enum)

`Decision | Pattern | Preference | Style | Habit | Insight | Context`

### 1.3 Types d'arêtes (enum)

`RELATES_TO | LEADS_TO | OCCURRED_BEFORE | PREFERS_OVER | EXEMPLIFIES | CONTRADICTS | REINFORCES | INVALIDATED_BY | EVOLVED_INTO | DERIVED_FROM | PART_OF`

---

## 2. Mapping mem0 metadata.type → AutoMem type + tags

Les rubriques mem0 utilisent un enum libre dans `metadata.type` (`decision`, `task_learning`, `anti_pattern`, `convention`, `user_preference`, `environmental`, `session_state`, `compact_summary`, `project_profile`, `bug_fix`). AutoMem impose 8 types fixes. Voici le mapping recommandé :

| mem0 metadata.type | AutoMem `type` | tags complémentaires |
|---|---|---|
| `decision` | `Decision` | — |
| `anti_pattern` | `Pattern` | `polarity:negative`, `kind:anti-pattern` |
| `convention` | `Style` | `kind:code-convention` |
| `user_preference` | `Preference` | — |
| `task_learning` | `Insight` | `kind:learning` |
| `bug_fix` | `Insight` | `kind:bug-fix` |
| `environmental` | `Context` | `kind:env`, `kind:tooling` |
| `session_state` | `Context` | `kind:session-state`, `ephemeral:true` |
| `compact_summary` | `Context` | `kind:compact-summary`, `ephemeral:true` |
| `project_profile` | `Context` | `kind:project-profile` |
| (nouveau) | `Habit` | workflows récurrents — ex. « always run pytest before commit » |

Le type `Habit` n'a pas d'équivalent direct mem0 — bonus AutoMem à exploiter pour capturer les workflows récurrents que l'utilisateur établit.

---

## 3. Scoping — DÉCISION FIGÉE le 26 mai 2026, élargie en v0.1.2

AutoMem n'a pas de scoping natif `user_id` / `app_id` / `run_id`. Plutôt que de tout tagger systématiquement (qui dupliquerait l'information sémantique déjà présente dans le `content`), on adopte une politique de **scoping minimal augmentée d'une convention `domain:` optionnelle** :

| Tag | Quand l'ajouter | Justification |
|---|---|---|
| `project:<slug>` | **Sur toutes les mémoires** | Permet la maintenance ("compte les décisions WhisperIt", "purge le projet X"), évite la pollution sémantique cross-projet, et boost les recall scopés. **Sémantiquement c'est un "context slug" — pas forcément un repo de code, peut être un thème de vie, une thématique de coaching, un journal, etc.** |
| `domain:<X>` | **Quand le type de contexte importe pour le filtrage** (optionnel) | Convention non-imposée : valeurs recommandées `code`, `personal`, `coaching`, `planning`, `learning`. Liste extensible (`writing`, `research`, `health`, …). Permet de filtrer "toutes mes décisions de coaching" sans avoir à parcourir les projets un par un. **Pas de détection automatique** — c'est à l'agent de proposer le tag pertinent lors du `store_memory`. |
| `session:<ses_id>` | **Uniquement sur les mémoires éphémères** (`Context` avec `kind:session-state` ou `kind:compact-summary`) | Permet de purger une session entière en bloc sans toucher aux mémoires durables |
| `ephemeral:true` | En complément de `session:` | Filtre rapide pour les opérations de cleanup |

**Pas de tag** `user:<X>` — l'utilisateur est seul sur son instance AutoMem. À ajouter si un jour l'instance est mutualisée.

**Pas de tag** `branch:<X>` — rarement pertinent au-delà du cas où une décision est strictement liée à une feature branch éphémère. Si une mémoire est branch-spécifique, le `content` doit l'expliquer.

**Le contexte narratif riche reste dans le `content`** — chaque mémoire commence idéalement par un préambule qui situe (« Sur WhisperIt en mai 2026, j'ai décidé X parce que Y »). Les tags ne remplacent pas le contexte, ils l'augmentent pour le filtrage rapide.

### Pourquoi `domain:` plutôt que des `project:` distincts pour chaque domaine ?

Parce que le projet est l'unité de **continuité** (« je travaille là-dessus depuis 3 mois »), alors que le domain est l'unité de **catégorie** (« ce sont des questions de carrière »). Un projet peut traverser plusieurs domains (ex. `project:reconversion-2026` mélange `domain:coaching`, `domain:planning`, `domain:learning`). Un domain peut couvrir plusieurs projets (ex. `domain:code` regroupe `project:WhisperIt` + `project:automem-plugin` + …). Les deux dimensions sont orthogonales.

### Résolution du `project:<slug>` (mise à jour 26 mai 2026, post-test réel)

Bug critique observé en conditions réelles : depuis Cowork, le cwd est un scratchpad `local-agent-mode-sessions/.../outputs` → l'ancien fallback `basename(cwd)` retournait `outputs` pour TOUTES les sessions Cowork, fragmentant les mémoires en deux buckets disjoints (Cowork=`outputs` vs CLI=`<slug>`). Fix livré :

| Étape | Mécanisme | Résultat |
|---|---|---|
| 1 | Override env var `AUTOMEM_PROJECT_ID` | Priorité absolue |
| 2 | Lookup `~/.automem-plugin/project_map.json` (cwd + self-healing par hash de remote URL) | Mapping explicite |
| 3 | **Walk-up** depuis cwd (max 6 niveaux) cherchant un marker | `.automem-project` (texte explicite) > `.git` (remote slug ou basename git root) > `automem.md` > `CLAUDE.md` > `AGENTS.md` |
| 4 | **Détection Cowork scratchpad** (path contient `local-agent-mode-sessions` ou se termine par `/Claude/.../outputs`) | Lecture de `~/.automem-plugin/cowork-default-project.txt` ou fallback sur le slug `cowork-default` |
| 5 | Fallback final | `basename(cwd)` |

Validé sur 7 scénarios de test en sandbox (cf. session du 26 mai 2026). Le Cowork bucket `cowork-default` est un compromis : il évite la fragmentation tout en restant identifiable. Pour avoir un vrai scope projet depuis Cowork, l'utilisateur a 3 options :
1. Exporter `AUTOMEM_PROJECT_ID=<slug>` dans son shell avant de lancer Cowork
2. Écrire le slug dans `~/.automem-plugin/cowork-default-project.txt`
3. Attendre Phase 7 → skill `/automem:switch-project <slug>` (override per-cwd dans project_map.json)

---

## 4. Architecture du plugin (5 couches)

```
┌──────────────────────────────────────────────────────────────┐
│  1. MCP server — AutoMem (auto-hébergé sur VPS)              │
│     Déjà déployé, déjà connecté à Cowork                    │
├──────────────────────────────────────────────────────────────┤
│  2. Hooks Claude Code — hooks/hooks.json                     │
│     10 événements câblés : SessionStart, UserPromptSubmit,   │
│     PreToolUse, PostToolUse, PreCompact, PostCompact, Stop,  │
│     TaskCompleted, SessionEnd, SubagentStop                  │
│     Chaque hook injecte une rubrique texte → contexte Claude │
├──────────────────────────────────────────────────────────────┤
│  3. Scripts utilitaires — scripts/                           │
│     _identity.sh, _project.py, _scope.py (tags),             │
│     _recall.py (wrapper HTTP recall_memory),                 │
│     _store.py (wrapper HTTP store_memory),                   │
│     load_settings.py, parse_automem_config.py                │
├──────────────────────────────────────────────────────────────┤
│  4. Skills — skills/*/SKILL.md                               │
│     ~15 skills : voir tableau §5                             │
├──────────────────────────────────────────────────────────────┤
│  5. Settings & state — ~/.automem-plugin/                    │
│     settings.json, project_map.json, file_hashes.json,       │
│     session-log.md, hooks.log                                │
└──────────────────────────────────────────────────────────────┘
```

---

## 5. Skills — porter, adapter, créer

| Skill | Source mem0 ? | Action |
|---|---|---|
| `onboard` | oui | **Adapter** — pas d'API key wizard (l'auth est au niveau MCP/VPS), pas de coding_categories. Garde l'import CLAUDE.md / AGENTS.md / .cursorrules / mem0.md → automem.md |
| `remember` | oui | **Porter trivialement** — `store_memory(type=<mapped>, tags=[scope...])` |
| `recall` (= peek) | oui | **Porter+enrichir** — exploiter `auto_decompose`, `expand_relations` |
| `tour` | oui | **Porter** — `recall_memory` paginé groupé par `type` |
| `stats` | oui | **Porter** — `check_database_health` (1 appel) + `recall_memory` paginé. Bonus : afficher les associations actives par type d'arête |
| `health` | oui | **Simplifier** — `check_database_health` natif (1 appel) + write/delete probe |
| `weave` (= dream) | oui mais réinventé | **Réinventer** — au lieu de pruner les contradictions, créer arêtes `CONTRADICTS`. Au lieu de delete les stale, set `t_invalid`. Au lieu de delete les low-confidence, set `importance=0`. Tisse au lieu de tailler. |
| `memory-reviewer` | oui | **Porter+enrichir** — propose des `associate_memories` à créer (read-only sur le graphe) |
| `pin` | oui | **Simplifier** — `update_memory(importance=1.0, tags=[...+'pinned'])`. Pas besoin de side-store. |
| `forget` | oui | **Porter** — `delete_memory(id)` direct. Pour soft-delete, `update_memory(t_invalid=now)` |
| `switch-project` | oui | **Porter** — écrit `~/.automem-plugin/project_map.json` |
| `list-projects` | oui | **Porter** — `recall_memory(tag_match=prefix, tags=['project:'])` puis dédup |
| `export` | oui | **Porter** — pagination recall + sérialisation |
| `import` | oui | **Porter** — parse + `store_memory` en boucle |
| `context-loader` | oui | **Porter+enrichir** — utiliser `queries[]` multi-query + `expand_relations=true` natif |
| **`associate` (NOUVEAU)** | non | Commande explicite : `/automem:associate <id1> <id2> <type> [strength]` |
| **`evolve` (NOUVEAU)** | non | Raccourci : `/automem:evolve <new_id> <old_id>` = `associate EVOLVED_INTO` + `update_memory(<old_id>, tags=[...+'invalidated'])` |

Skills mem0 abandonnés : `setup_coding_categories` (concept absent d'AutoMem), `mem0` SDK reference (remplacer par un skill `automem-sdk` séparé si pertinent un jour).

---

## 6. Hooks — table d'événements

Tableau quasi identique à mem0, seul le contenu des rubriques diffère (syntaxe `store_memory`/`recall_memory` au lieu de `add_memory`/`search_memories`).

| Événement | Script | Fonction |
|---|---|---|
| `SessionStart: startup\|resume\|compact` | `on_session_start.sh` | Bannière d'identité (user, project, branch, count via `check_database_health` ou `recall_memory(limit=1, tags=['project:X'])`), rubrique de recall selon source |
| `UserPromptSubmit` | `on_user_prompt.sh` | Détection regex (stack traces, file paths, intents) + rubrique 1×/session via `$AUTOMEM_STATE_DIR/rubric_${SESSION_ID}.flag` (~/.automem-plugin/state/). Pas de pré-fetch (AutoMem MCP-only). |
| `PreToolUse: Write\|Edit` | `block_memory_write.sh` | Bloque writes vers `*/.claude/*/MEMORY.md` |
| `PreToolUse: Bash` | `on_git_commit_capture.sh` | Pre-flight git commit |
| `PreToolUse: Read` | `on_file_read.sh` | Pré-fetch via `_recall.py` avec `active_path=<file>` (bonus AutoMem) |
| `PreToolUse: mcp__automem__store_memory` | `enforce_metadata_defaults.sh` | Patche le payload : ajoute tags `scope:...`, `branch:...`, `source:auto_capture` si absents |
| `PostToolUse: mcp__automem__*` | `on_post_tool_use.sh` | Stats session (`session_stats.py`) |
| `PostToolUse: Bash` | `on_post_commit.sh` + `on_bash_output.sh` | Capture commit + détection stack traces + pré-fetch via `_recall.py` |
| `PreCompact` | `on_pre_compact.sh` | Rubrique détaillée extract 0-3 facts |
| `PostCompact: manual\|auto` | `on_post_compact.sh` | Rubrique recovery (relancer recall) |
| `Stop` | `on_stop.sh` | Rubrique courte « store 0-2 durable facts » |
| `TaskCompleted` | `on_task_completed.sh` | Rubrique « store 0-2 learnings » |
| `SessionEnd` | `on_session_end.sh` | Snapshot stats → `~/.automem-plugin/session-log.md` |
| `SubagentStop` | `on_subagent_stop.sh` | Rubrique store + sync stats |

---

## 7. Settings — `~/.automem-plugin/settings.json`

```json
{
  "auto_save": true,
  "auto_recall": true,
  "recall_limit": 10,
  "retention_session_days": 90,
  "confidence_threshold": 0.3,
  "importance_threshold": 0.3,
  "output_style": "compact",
  "debug": false,
  "skip_tools": ["Read", "Glob", "Grep"],
  "capture_tools": ["Edit", "Write", "Bash"],
  "weave_auto_associate": true,
  "expand_relations_default": false
}
```

Trois clés nouvelles vs mem0 : `importance_threshold` (pruning), `weave_auto_associate` (autoriser le skill weave à créer des arêtes sans confirmation), `expand_relations_default` (activer multi-hop par défaut dans context-loader).

---

## 8. Roadmap révisée — par phase

| Phase | Durée | Livrable |
|---|---|---|
| **Phase 0 — Prép** ✅ | 30 min | Inspection serveur, validation surface AutoMem, this doc |
| **Phase 1 — MVP** | 2-3 h | `plugin.json`, `.mcp.json` (optionnel si déjà configuré), `_identity.sh` (avec décision scoping), `_project.py`, `_scope.py`, `on_session_start.sh`, `on_stop.sh`, skill `onboard` adapté → **auto-load au démarrage + auto-save fin de tour** |
| **Phase 2 — Heuristiques** | 2-3 h | `on_user_prompt.sh` complet, `_recall.py` wrapper HTTP, rubriques dédupliquées, regex de détection (stack traces, file paths, intents) → **détection contextuelle + pré-fetch** |
| **Phase 3 — Auto-capture** | 1-2 h | `auto_import.py`, `enforce_metadata_defaults.sh`, `block_memory_write.sh` |
| **Phase 4 — Compaction** ✅ | 1-2 h | `on_pre_compact.sh` (rubrique extract durable facts) + recovery + capture intégrés dans `on_session_start.sh` case `compact` (en v0.1.5 — PostCompact n'est PAS un événement officiel Claude Code, donc le hook séparé `on_post_compact.sh` ne firerait jamais ; toute la logique post-compact passe par `SessionStart:compact` qui, lui, fire bien). Note : `capture_compact_summary.py` du plan initial est abandonné car AutoMem est MCP-only — la capture est déléguée à Claude via MCP via la rubrique injectée. |
| **Phase 5 — Skills core** | 3-4 h | `remember`, `recall`, `tour`, `stats`, `health` |
| **Phase 6 — Skills graphe** | 4-5 h | `weave` (réinventé), `associate` (nouveau), `evolve` (nouveau), `pin`, `forget`, `memory-reviewer` |
| **Phase 7 — Skills orchestration** | 3-4 h | `switch-project`, `list-projects`, `context-loader` (avec expand_relations), `export`, `import`, hooks de confort (`on_file_read`, `on_bash_output`, `on_post_commit`) |
| **Phase 8 — Polish** | variable | README, `setup-automem` skill, output style, tests |

**Total estimé** : 17-23 h. **MVP utilisable** dès Phase 1+2 (~5 h).

---

## 9. Décisions ouvertes à trancher

1. ~~**Convention de scoping par tags**~~ ✅ **FIGÉE le 26 mai 2026** — scoping minimal : `project:<slug>` partout + `session:<id>` sur l'éphémère seulement (cf. §3 mis à jour).
2. **Mapping `anti_pattern`** — Type `Pattern` + tag `polarity:negative` est ma recommandation. Alternative : type `Insight` + tag `kind:anti-pattern`. Préférence à confirmer.
3. **`automem.md` vs `mem0.md`** — Si tu as déjà des fichiers `mem0.md` dans certains projets WhisperIt, on garde le nom pour compat ou on bascule sur `automem.md` ?
4. ~~**Wrapper HTTP `_recall.py`**~~ ✅ **FIGÉ le 26 mai 2026** — AutoMem est MCP-only (cf. §0bis), pas de wrapper HTTP nécessaire ni possible. Tous les hooks passent par injection de rubriques.
5. **`SubagentStop` vs `Stop`** — Mêmes rubriques ou différenciation ?
6. **Auto-associate dans `weave`** — Le skill weave peut-il créer des arêtes `CONTRADICTS` automatiquement (avec confirmation par batch), ou toujours demander à l'utilisateur arête par arête ?

---

## 10. Annexes — fichiers de référence

- Plan V1 obsolète : `/Users/sbellon/Library/Application Support/Claude/local-agent-mode-sessions/.../outputs/automem-portage-plan.md` (à archiver, garder pour traçabilité)
- Mémoires AutoMem de référence (5 stockées le 25 mai 2026, IDs `b29a0b89`, `1e0ecd9f`, `d9d0a033`, `7cc6ab57`, `ab1429eb`) — tissées par 4 arêtes
- Code source plugin mem0 v0.2.4 — réutiliser comme blueprint pour `hooks.json`, `_identity.sh`, `_project.py`, scripts génériques (rename mem0→automem)

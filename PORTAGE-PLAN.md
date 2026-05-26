# Plan de portage AutoMem — Plugin Claude Code / Cowork

> Version 2 du plan, **révisée le 26 mai 2026** après inspection des vrais schémas MCP d'AutoMem. La V1 supposait à tort qu'AutoMem clonait la surface mem0 — elle est obsolète.
>
> Le document de référence de la V1 reste disponible dans le scratchpad sous `automem-portage-plan.md` mais ne doit plus servir de guide d'implémentation.

---

## 0. Ce qui a changé entre V1 et V2

Trois découvertes majeures de la session du 25 mai 2026 :

1. **AutoMem n'est pas un clone mem0.** Stack FalkorDB + Qdrant, surface MCP `store_memory` / `recall_memory` / `associate_memories` / `check_database_health`. Pas de `user_id`/`agent_id`/`app_id`/`run_id` natifs.
2. **Les trois "gaps" identifiés en V1 sont invalidés.** `update_memory` accepte content + tags + metadata + importance, `t_valid`/`t_invalid` sont natifs, et `recall_memory` a `sort`/`context_*`/`priority_ids`.
3. **AutoMem a des features uniques** absentes de mem0 et qui méritent d'être au cœur du plugin : `associate_memories` avec 11 types d'arêtes typées, `expand_relations` dans `recall_memory`, boost contextuel natif via `active_path` / `language` / `context_tags`. (Note v0.1.8 : `expand_entities` est aussi exposé par AutoMem mais le NER serveur classe mal le français et le jargon technique — bruit ~30-50% de tags `entity:*` bidons par mémoire. À ne pas utiliser tant que le NER upstream n'est pas amélioré, ou désactivé côté serveur. Cf. §X.)

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
| `anti_pattern` | `Insight` | `kind:anti-pattern` |
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

### Résolution du `project:<slug>` (mise à jour 26 mai 2026, v0.1.7 simplifié)

Mécanisme final, par ordre de priorité :

| Étape | Mécanisme | Pourquoi |
|---|---|---|
| 1 | Env var `AUTOMEM_PROJECT_ID` | Override ephemeral per-shell, utile pour un one-off |
| 2 | **`~/.automem-plugin/active-project.txt`** (écrit par `/automem:switch-project`) | **Le mécanisme principal côté utilisateur.** Un seul slug, persiste across sessions, change uniquement quand l'utilisateur le décide. Pas de magie cwd. |
| 3 | `~/.automem-plugin/project_map.json` (lookup par cwd + self-healing hash remote) | Mécanisme avancé : différents slugs selon le repo. Pour quand tu travailles sur plusieurs projets git en parallèle et veux que chacun ait son propre scope. |
| 4 | Walk-up cwd (max 6 niveaux) pour markers | `.automem-project` > `.git` (slug owner-repo) > `CLAUDE.md` > `AGENTS.md`. Auto-détection pour les sessions CLI lancées dans un projet. Note v0.3.1 : `automem.md` / `mem0.md` retirés — tool-specific memory-config, hors scope OS memory layer. |
| 5 | `~/.automem-plugin/default-context.txt` (back-compat aussi `cowork-default-project.txt`) | Slug "par défaut" pour les cas où rien d'autre ne s'applique. Sinon littéral `default`. |

### Pourquoi v0.1.6 → v0.1.7 a simplifié ?

En v0.1.6, `/automem:switch-project` écrivait dans `project_map.json` un mapping `cwd → slug`. Problème observé en usage réel : depuis Cowork, le cwd est `local_<UUID-volatile>/outputs/` — un sous-dossier dont l'UUID change à chaque session. Donc le mapping ne survivait pas à la prochaine session.

Au-delà du bug, le design lui-même était trop subtil pour l'intention courante de l'utilisateur. Quand on tape `/automem:switch-project coaching-2026`, on veut dire « pour tout ce qui suit, le scope est coaching-2026 ». Pas « pour ce répertoire-ci, le scope est coaching-2026 ».

v0.1.7 ajoute donc `active-project.txt` (priorité 2 dans la cascade) comme override **global** : un fichier, une ligne, un slug. `/automem:switch-project` écrit là. `project_map.json` reste disponible (priorité 3) pour le cas d'usage avancé où tu veux vraiment binder par cwd.

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
| `onboard` | oui | **Adapter** — pas d'API key wizard (l'auth est au niveau MCP/VPS), pas de coding_categories. Garde l'import CLAUDE.md / AGENTS.md / .cursorrules (automem.md / mem0.md retirés en v0.3.1). |
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

## 8. Roadmap — re-priorisée par valeur d'usage (révisée 26 mai 2026 v0.1.9)

**Note de design** : la roadmap initiale était structurée par phases (héritage du plan de portage mem0), fidèle au plan d'origine par souci d'exhaustivité. Une réflexion sur l'usage réel d'AutoMem comme **memory layer OS principal** (cross-domain : code + vie + coaching + journal + planning, pas seulement assistant dev) montre que plusieurs phases du plan d'origine n'apportent pas de valeur dans ce cas d'usage. On bascule la roadmap restante sur une structure par **Tier d'usage**.

### Acquis (déjà livré, ne plus toucher sauf bug fix)

| Élément | Version | Statut |
|---|---|---|
| **Phase 1 — MVP** (plugin.json, _identity, _project, on_session_start, on_stop, skill onboard) | v0.1.0 → v0.1.5 (fix scoping + state dir) | ✅ |
| **Phase 2 — Heuristiques** (on_user_prompt.sh : ERROR, FILE_PATHS, RESUME, REMEMBER FR/EN + rubric dédup 1×/session) | v0.1.1 | ✅ |
| **Phase 4 — Compaction** (on_pre_compact + recovery/capture intégrés dans SessionStart:compact) | v0.1.3 → v0.1.5 (drop PostCompact non-officiel) | ✅ |
| **Skills core** : onboard, remember, recall, switch-project (simplifié global), health | v0.1.0 → v0.1.7 | ✅ |
| Audit fixes (perms, state dir, debug visibility), garde-fous NER | v0.1.5 → v0.1.8 | ✅ |

### Tier 1 — Très haute valeur, à faire maintenant (v0.1.9)

Ces 4 skills débloquent vraiment AutoMem en tant que graphe vivant, sans lesquels le plugin reste un système plat « mémoire-vectorielle + tags ».

- `/automem:associate <id1> <id2> <type> [strength]` — créer une arête typée entre deux mémoires (parmi les 11 types : `RELATES_TO`, `LEADS_TO`, `OCCURRED_BEFORE`, `PREFERS_OVER`, `EXEMPLIFIES`, `CONTRADICTS`, `REINFORCES`, `INVALIDATED_BY`, `EVOLVED_INTO`, `DERIVED_FROM`, `PART_OF`). Wrapper sur `associate_memories` MCP. Trivial (~15 min).
- `/automem:evolve <new_id> <old_id>` — raccourci pour marquer qu'une décision en remplace une autre : crée l'arête `EVOLVED_INTO` + tag `invalidates:<new>` sur l'ancienne pour permettre le filtrage. ~15 min.
- `/automem:pin <id_ou_query>` — protection d'une mémoire structurelle : set `importance=1.0` + tag `pinned`. Empêche les pruning futurs. Flag `--unpin` pour retirer. ~15 min.
- `/automem:forget <id_ou_query>` — delete avec confirmation. Flag `--soft` pour set `t_invalid=now` au lieu de delete (réversible). Flag `--force` pour skip la confirmation. ~15 min.

Total Tier 1 : **~1h de code**.

### Tier 2 — Valeur élevée (✅ livré v0.2.0)

- `/automem:list-projects` ✅ — vue d'ensemble des contextes actifs (recall global + extraction client-side des tags `project:*`, dédup, count par projet). Flags `--with-types`, `--all-time`, `--since`. v0.2.0.
- `/automem:weave` ✅ — consolidation par tissage : crée arêtes `REINFORCES`/`CONTRADICTS`/`EVOLVED_INTO` au lieu de pruner, soft-expire les stale (`t_invalid`), downweight les low-confidence (`importance=0`). Mode dry-run par défaut + `--apply` + `--auto`. Skip pinned. Réclame ~50+ mémoires par projet pour être vraiment utile (aujourd'hui 15-20). v0.2.0.

### Tier 3 — Confort, valeur modérée (✅ livré v0.3.0)

Initialement marqué optionnel ("à faire si l'usage le demande"), finalement livré dans la foulée pour avoir un plugin 100% complet sur lequel faire les évals d'usage réel (logique Sébastien : « finir puis évaluer plutôt que coder spéculativement plus tard »).

- `/automem:tour` ✅ — navigation paginée par les 8 types AutoMem, sortie groupée + decorations (pinned, importance, kind:, INVALIDATED). Flags `--type`, `--since`, `--limit`, `--include-ephemeral`, `--include-invalidated`. v0.3.0.
- `/automem:stats` ✅ — distribution quantitative par type/domain/age/importance/confidence, pinned/ephemeral/invalidated counts, mode `--weekly`/`--monthly` pour activity over time. Mode `--export-json` pour scripting. v0.3.0.
- `/automem:memory-reviewer` ✅ — audit READ-ONLY identifiant duplicates / contradictions / stale / low-conf / orphans / type-issues, sortie compact avec example IDs + recommandation next action (weave, associate, evolve). Pas de mutation, jamais. v0.3.0.
- `/automem:context-loader` ✅ — multi-recall enrichi (3 angles parallèles + expand_relations) avec output structuré par type + relations + synthesis paragraph. Mode agent-driven (internalise sans afficher) ou user-driven (affiche le bloc structuré). Flag `--depth=0|1|2` pour contrôler l'expansion graph. v0.3.0.

### Tier 4 — Abandonné, non pertinent pour ce cas d'usage

Volontairement écartés. Si l'usage évolue (genre tu décides un jour d'utiliser AutoMem aussi comme assistant code spécialisé), on rouvre.

- **Phase 3 entière** (auto_import.py, enforce_metadata_defaults.sh, block_memory_write.sh) : défense en profondeur orientée dev workflow. `auto_import` ne s'applique pas à un memory layer OS qui tourne souvent dans un scratchpad sans `CLAUDE.md`. `enforce_metadata_defaults` est marginal vu que la rubrique `on_stop.sh` rappelle déjà les tags. `block_memory_write` protège contre une attaque qui ne se produit pas (Claude ne crée pas spontanément de `MEMORY.md`).
- **Hooks confort code** (`on_file_read.sh` boost `active_path`, `on_bash_output.sh` détection stack traces, `on_post_commit.sh` capture git commit) : optimisations spécifiques au dev workflow. Neutres voire encombrants pour un usage cross-domain.
- **`/automem:export` et `/automem:import`** : portabilité non urgente. Backup possible via FalkorDB dump direct côté VPS si besoin.
- **Phase 8 — `setup-automem` skill, output style, tests** : polish. À voir après usage réel pendant quelques semaines.

### Total restant après Tier 1 + Tier 2 sélectif

~3-4 h de code pour avoir 95% de la valeur d'AutoMem comme memory layer OS personnel. Le reste est optionnel ou hors-scope.

---

## 8.5. Bruit NER serveur (open issue upstream)

AutoMem applique un NER côté serveur sur le `content` de chaque mémoire et ajoute des tags `entity:<bucket>:<value>` automatiques. Observé en usage réel sur 15 mémoires : ~30-50% des tags ajoutés sont des faux positifs, en particulier sur du texte français (perte des diacritiques) et du jargon technique (acronymes, noms composés). Échantillon : `entity:concepts:s-bastien` (Sébastien), `entity:organizations:postcompact` (label technique), `entity:organizations:context` / `fallback` / `pas-de` / `uniquement` (mots communs mal classés), `entity:people:claude-code` (tool mal classé en personne).

**Impact réel** : faible tant qu'on ne fait pas `expand_entities=true` dans les recall. Le scoring de `recall_memory` dépend principalement de l'embedding (sur le `content`) et des tags qu'on contrôle (`project:`, `domain:`, `kind:`). Les `entity:*` sont passifs. **Critique** uniquement si activé via `expand_entities`.

**Décision v0.1.8** : ne pas exposer `--entities` dans `/automem:recall` tant que le NER serveur n'est pas amélioré ou désactivé. Si l'utilisateur a accès à la config AutoMem (variable d'env, fichier YAML, etc.), désactiver le NER élimine la pollution à la source. Cleanup rétroactif des `entity:*` tags faisable via boucle `recall_memory` → `update_memory` (script futur si besoin).

À tester côté serveur : presence de flags type `AUTOMEM_DISABLE_NER`, `ENABLE_ENTITY_EXTRACTION=false`, ou réglage dans le YAML d'AutoMem.

## 9. Décisions ouvertes à trancher

Toutes tranchées au 26 mai 2026 (v0.3.1).

1. ~~**Convention de scoping par tags**~~ ✅ **FIGÉE** — scoping minimal : `project:<slug>` partout + `session:<id>` sur l'éphémère seulement (cf. §3).
2. ~~**Mapping `anti_pattern`**~~ ✅ **FIGÉE en v0.3.1** — type `Insight` + tag `kind:anti-pattern` (au lieu de `Pattern` + `polarity:negative`). Raison : cohérence avec le mapping existant (task_learning → Insight + kind:learning ; bug_fix → Insight + kind:bug-fix). Le type `Pattern` reste réservé aux abstractions positives observées.

 — Type `Pattern` + tag `polarity:negative` est ma recommandation. Alternative : type `Insight` + tag `kind:anti-pattern`. Préférence à confirmer.
3. ~~**`automem.md` vs `mem0.md`**~~ ✅ **FIGÉE en v0.3.1 — retirés du scope**. Les deux fichiers étaient des mémoires-configs tool-specific (mem0 / automem-as-mem0-clone), pas pertinents pour AutoMem positionné comme OS memory layer cross-domain. Walk-up `_project.py` et scan `onboard` les ignorent désormais. CLAUDE.md / AGENTS.md / .cursorrules / .windsurfrules conservés (markers agent-runtime universels, pas config-mémoire).
4. ~~**Wrapper HTTP `_recall.py`**~~ ✅ **FIGÉ** — AutoMem est MCP-only (cf. §0bis), pas de wrapper HTTP nécessaire ni possible. Tous les hooks passent par injection de rubriques.

5. ~~**SubagentStop vs Stop**~~ ✅ **FIGÉE en v0.3.1 — SubagentStop intentionnellement non câblé**. Raison : un sous-agent (Task tool) est presque toujours délégué pour une tâche ciblée (recherche, audit, lookup parallèle) et retourne un résultat synthétique à l'agent principal. Câbler SubagentStop avec la même rubrique que Stop produirait (a) des stores fragmentés sans contexte global, (b) une notification `> memory ops` invisible au user (le sous-agent ne renvoie pas ses hooks), (c) un double-bump du compteur de stores qui fausse le weave périodique. L'agent principal a la vue d'ensemble, c'est lui qui doit synthétiser et stocker. Si l'usage évolue vers des sous-agents en deep-research autonome, on rouvre la question.

6. ~~**Auto-associate dans `weave`**~~ ✅ **FIGÉE en v0.3.1 — Option A (statu quo)** + enhancement weave-pending-review. `weave --auto` skip volontairement les CONTRADICTS et EVOLVED_INTO parce que (a) l'heuristique de détection lexicale est fragile et faux positifs probables, (b) en mode silent agent-driven, l'utilisateur n'aurait aucune visibilité sur les arêtes créées sans aller chercher manuellement. Enhancement : quand `--auto` détecte ce type de candidats, il stocke un mémo `Context kind:weave-pending-review` qui résume les paires en attente. Le hook SessionStart suivant détecte ces pending reviews récents (< 7 jours) et les surface dans la rubric pour proposer un `/automem:weave --apply` interactif. À ré-évaluer après accumulation d'usage et de données (50+ mémoires par projet) — si les heuristiques s'avèrent fiables, on pourra basculer en auto-application.
5. **`SubagentStop` vs `Stop`** — Mêmes rubriques ou différenciation ?
6. **Auto-associate dans `weave`** — Le skill weave peut-il créer des arêtes `CONTRADICTS` automatiquement (avec confirmation par batch), ou toujours demander à l'utilisateur arête par arête ?

---

## 10. Annexes — fichiers de référence

- Plan V1 obsolète : `/Users/sbellon/Library/Application Support/Claude/local-agent-mode-sessions/.../outputs/automem-portage-plan.md` (à archiver, garder pour traçabilité)
- Mémoires AutoMem de référence (5 stockées le 25 mai 2026, IDs `b29a0b89`, `1e0ecd9f`, `d9d0a033`, `7cc6ab57`, `ab1429eb`) — tissées par 4 arêtes
- Code source plugin mem0 v0.2.4 — réutiliser comme blueprint pour `hooks.json`, `_identity.sh`, `_project.py`, scripts génériques (rename mem0→automem)

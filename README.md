# automem-plugin

Plugin Claude Code qui transforme [AutoMem](https://github.com/) (instance auto-hébergée sur VPS, stack FalkorDB + Qdrant) en mémoire persistante automatisée pour Claude — auto-load au début de session, capture heuristique des décisions et apprentissages, consolidation par graphe.

Inspiré de l'architecture du plugin officiel `mem0` v0.2.4, mais radicalement adapté à la surface MCP d'AutoMem (qui n'est PAS compatible mem0 malgré la finalité voisine).

## Status

En cours de construction. Voir [`PORTAGE-PLAN.md`](./PORTAGE-PLAN.md) pour la cible, les décisions de design et la roadmap.

## Stack cible

| Couche | Outil |
|---|---|
| MCP serveur | AutoMem (auto-hébergé) — FalkorDB graphe + Qdrant vecteurs 1024d |
| Surface MCP | `store_memory` / `recall_memory` / `associate_memories` / `update_memory` / `delete_memory` / `check_database_health` |
| Hooks Claude Code (shipped) | `SessionStart`, `UserPromptSubmit`, `PreCompact`, `Stop` |
| Hooks Claude Code (planned) | `PreToolUse`, `PostToolUse`, `SubagentStop`, `Notification`, `SessionEnd` |
| Skills (shipped) | `/automem:onboard`, `/automem:remember`, `/automem:recall` |
| Skills (planned) | `/automem:tour`, `/automem:stats`, `/automem:health`, `/automem:weave`, `/automem:associate`, `/automem:pin`, `/automem:forget`, `/automem:context-loader`, `/automem:switch-project` |

## Structure du repo

```
.claude-plugin/      # plugin.json (manifest Claude Code)
hooks/               # hooks.json (déclaration des hooks)
scripts/             # implémentations bash + python des hooks
skills/              # skills /automem:* exposés à l'utilisateur
PORTAGE-PLAN.md      # design doc / roadmap
```

## Installation (dev local)

Le plugin n'est pas encore publié sur un marketplace public. Voie recommandée pour le tester en local : **marketplace local + CLI `claude`**.

L'upload ZIP via l'UI Cowork (sidebar Customize → Plugins → Upload) déclenche actuellement un « Plugin validation failed » non détaillé. La CLI `claude plugin install`, qui partage la config `~/.claude/` avec Cowork, fait passer le plugin sans broncher — et Cowork le récupère au redémarrage.

```bash
# 1. Cloner le repo
git clone https://github.com/sebastienBellon/automem_plugin_claude.git ~/Downloads/automem_plugin_claude

# 2. Créer un marketplace local qui pointe vers le clone
mkdir -p ~/Downloads/automem-marketplace/.claude-plugin
cat > ~/Downloads/automem-marketplace/.claude-plugin/marketplace.json <<'EOF'
{
  "name": "local-automem",
  "owner": { "name": "Sébastien Bellon" },
  "plugins": [
    { "name": "automem", "source": "../automem_plugin_claude" }
  ]
}
EOF

# 3. Enregistrer le marketplace + installer
claude plugin marketplace add ~/Downloads/automem-marketplace
claude plugin install automem@local-automem
```

Redémarre Cowork après installation. Le plugin est désormais disponible côté CLI **et** côté Cowork (même config `~/.claude/`). Une bannière `AutoMem Active | project=… | branch=…` apparaîtra au prochain `SessionStart`.

### Mise à jour

Le marketplace local lit le plugin par chemin (pas par checkout d'un commit), donc tes modifications locales sont immédiatement visibles. Après un `git pull` (ou pour récupérer une nouvelle version après modifs locales) :

```bash
claude plugin update automem
```

## Configuration

Le manifest expose deux `userConfig` optionnels (`rest_base_url`, `rest_auth_header`) prévus pour le jour où AutoMem exposera une REST en complément du MCP. **Pour l'instant, laisse-les vides** — AutoMem est MCP-only, les hooks délèguent tous les appels à Claude via MCP, aucun appel REST direct depuis bash n'est fait.

### Scoping (tags `project:` et `domain:`)

Toutes les mémoires sont scopées par tag `project:<slug>`. Le slug est résolu dans l'ordre :

1. Variable d'environnement `AUTOMEM_PROJECT_ID`
2. Lookup `~/.automem-plugin/project_map.json` (`cwd → project_id`)
3. Walk-up depuis le `cwd` cherchant `.automem-project`, `.git`, `automem.md`, `CLAUDE.md`, `AGENTS.md`
4. Fallback : `default` (slug neutre — pas un nom de repo, pas un dossier scratchpad)

Convention optionnelle `domain:<X>` pour filtrer par catégorie : `code`, `personal`, `coaching`, `planning`, `learning` (liste extensible). Détails dans [`PORTAGE-PLAN.md`](./PORTAGE-PLAN.md) §3.

### État local

Le plugin écrit dans `~/.automem-plugin/` :

- `settings.json` — auto_save, auto_recall, recall_limit, retention_session_days, etc. (éditable)
- `project_map.json` — overrides explicites `cwd → project_id` (édité par `/automem:switch-project` quand livré)
- `state/` — session id, stats, rubric flags, recent reads (interne au plugin)
- `hooks.log` — logs des hooks quand `AUTOMEM_DEBUG=true`

## License

MIT — voir [`LICENSE`](./LICENSE).

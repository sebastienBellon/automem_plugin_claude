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
| Hooks Claude Code | `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PreCompact`, `PostCompact`, `Stop`, `TaskCompleted`, `SessionEnd`, `SubagentStop` |
| Skills | `/automem:remember`, `/automem:recall`, `/automem:weave`, `/automem:associate`, `/automem:pin`, `/automem:forget`, `/automem:stats`, `/automem:health`, `/automem:context-loader`, `/automem:onboard`, ... |

## Structure du repo

```
.claude-plugin/      # plugin.json (manifest Claude Code)
hooks/               # hooks.json (déclaration des hooks)
scripts/             # implémentations bash + python des hooks
skills/              # skills /automem:* exposés à l'utilisateur
PORTAGE-PLAN.md      # design doc / roadmap
```

## Installation (dev local)

Le plugin n'est pas encore publié. Pour le tester localement :

```bash
# Cloner le repo
git clone https://github.com/sebastienBellon/automem_plugin_claude.git
cd automem_plugin_claude

# Référencer le plugin depuis ~/.claude/settings.json
# (voir la doc Claude Code "plugins" pour les options exactes de chargement local)
```

Configurer ensuite les variables `rest_base_url` et `rest_auth_header` exposées par `plugin.json` si tu veux utiliser le pré-fetch REST direct en plus du canal MCP.

## License

MIT — voir [`LICENSE`](./LICENSE).

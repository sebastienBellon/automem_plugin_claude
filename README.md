# automem-plugin

Plugin Claude Code / Cowork qui transforme [AutoMem](https://github.com/) (instance auto-hébergée sur VPS, stack FalkorDB + Qdrant) en mémoire persistante automatisée pour Claude — auto-load au début de session, capture heuristique des décisions et apprentissages, consolidation par graphe.

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

## License

À définir.

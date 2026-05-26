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
| Skills (shipped) | `/automem:onboard`, `/automem:remember`, `/automem:recall`, `/automem:switch-project`, `/automem:health`, `/automem:associate`, `/automem:evolve`, `/automem:pin`, `/automem:forget`, `/automem:list-projects`, `/automem:weave`, `/automem:tour`, `/automem:stats`, `/automem:memory-reviewer`, `/automem:context-loader` |

## Structure du repo

```
.claude-plugin/      # plugin.json (manifest Claude Code)
hooks/               # hooks.json (déclaration des hooks)
scripts/             # implémentations bash + python des hooks
skills/              # skills /automem:* exposés à l'utilisateur
PORTAGE-PLAN.md      # design doc / roadmap
```

## Installation

Le repo est son propre **marketplace** (descripteur `.claude-plugin/marketplace.json` à la racine, source `github`). Une seule commande pour ajouter le marketplace, une pour installer le plugin :

```bash
claude plugin marketplace add sebastienBellon/automem_plugin_claude
claude plugin install automem@automem
```

Redémarre Cowork / ouvre une nouvelle session CLI après installation. Une bannière `AutoMem Active | project=… | branch=…` apparaîtra au prochain `SessionStart`.

### Repo privé

Si le repo est privé, l'install manuelle ci-dessus réutilise tes credentials git existants (`gh` CLI, ssh-agent, macOS Keychain, etc.) — rien à configurer si `git clone git@github.com:sebastienBellon/automem_plugin_claude.git` marche déjà chez toi.

Pour activer les **auto-updates au démarrage** (non-interactifs), il faut un token dans l'environnement :

```bash
export GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
```

### Mise à jour

```bash
claude plugin marketplace update automem
```

Re-fetch le repo depuis GitHub et applique la dernière version disponible.

### Alternative : install local (dev)

Si tu hackes activement le plugin et veux voir tes modifs sans push :

```bash
# Cloner + créer un marketplace local qui pointe vers le clone
git clone https://github.com/sebastienBellon/automem_plugin_claude.git ~/dev/automem_plugin_claude

mkdir -p ~/dev/automem-marketplace/.claude-plugin
cat > ~/dev/automem-marketplace/.claude-plugin/marketplace.json <<'EOF'
{
  "name": "local-automem",
  "owner": { "name": "Sébastien Bellon" },
  "plugins": [
    { "name": "automem", "source": "../automem_plugin_claude" }
  ]
}
EOF

claude plugin marketplace add ~/dev/automem-marketplace
claude plugin install automem@local-automem
```

## Configuration

Le manifest expose deux `userConfig` optionnels (`rest_base_url`, `rest_auth_header`) prévus pour le jour où AutoMem exposera une REST en complément du MCP. **Pour l'instant, laisse-les vides** — AutoMem est MCP-only, les hooks délèguent tous les appels à Claude via MCP, aucun appel REST direct depuis bash n'est fait.

### Scoping (tags `project:` et `domain:`)

Toutes les mémoires sont scopées par tag `project:<slug>`. Le slug est résolu dans l'ordre (premier non-vide gagne) :

1. Variable d'environnement `AUTOMEM_PROJECT_ID` (ephemeral, per-shell)
2. **`~/.automem-plugin/active-project.txt`** — slug actif global, écrit par `/automem:switch-project`. Le mécanisme principal côté utilisateur : un slug, persiste across sessions, change à la demande.
3. `~/.automem-plugin/project_map.json` (mécanisme avancé : binding par cwd, utile si tu veux différents slugs pour différents repos git)
4. Walk-up depuis le `cwd` cherchant `.automem-project`, `.git`, `CLAUDE.md`, `AGENTS.md`
5. Fallback : contenu de `~/.automem-plugin/default-context.txt` si présent, sinon littéral `default`

Convention optionnelle `domain:<X>` pour filtrer par catégorie : `code`, `personal`, `coaching`, `planning`, `learning` (liste extensible). Détails dans [`PORTAGE-PLAN.md`](./PORTAGE-PLAN.md) §3.

### État local

Le plugin écrit dans `~/.automem-plugin/` :

- `settings.json` — auto_save, auto_recall, recall_limit, retention_session_days, etc. (éditable)
- `active-project.txt` — slug du projet actif, géré par `/automem:switch-project` (priorité 2 dans la cascade)
- `default-context.txt` — fallback de dernier recours pour le slug (priorité 5)
- `project_map.json` — overrides avancés `cwd → project_id` (priorité 3, optionnel)
- `state/` — session id, stats, rubric flags, recent reads (interne au plugin)
- `hooks.log` — logs des hooks quand `AUTOMEM_DEBUG=true`

## License

MIT — voir [`LICENSE`](./LICENSE).

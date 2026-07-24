# Publishing the CONFESSION Guild agents

Exact CLI sequence to create the workspace and init → save → publish → workspace-add all three agents. The binary is `npx @guildai/cli` (NOT GNU Guile's `guild`). Guild auth lives in CLI state (`guild auth login`) — there is no env var. Pin the CLI version at the event for reproducibility (dailygate pinned `@guildai/cli@0.12.3`).

Set an alias for the session so every command is unambiguous:

```bash
alias guild='npx --yes @guildai/cli@latest'
guild auth login          # opens the browser; authenticates the CLI
guild auth whoami         # confirm the signed-in owner; note it as $OWNER below
```

## 1. Create the workspace

```bash
guild workspace create confession
# → creates the workspace $OWNER/confession
# The engine reads GUILD_WORKSPACE=confession/confession from .env; if your
# owner slug differs, set GUILD_WORKSPACE to <owner>/confession to match.
```

## 2. Init + save + publish each agent

`guild agent init` creates the agent record and writes a CLI-managed `guild.json` into the directory. The `agent.ts`, `package.json`, and `tsconfig.json` already in each directory ARE the agent — keep them; do not let a template overwrite `agent.ts`. Run these from `guild-agents/`:

```bash
for name in builder-l0 builder-l1 auditor; do
  ( cd "$name"

    # Create the agent record + guild.json in this dir. The scaffold may drop a
    # starter agent.ts/package.json — restore ours from git before saving.
    guild agent init --name "confession-$name" --template LLM --category development
    git checkout -- agent.ts package.json tsconfig.json 2>/dev/null || true

    # Validate the build, then publish to the organization.
    guild agent save --all --message "CONFESSION $name" --wait --publish
  )
done
```

`--wait` blocks until the build validation passes; `--publish` makes the version available to your organization. `--all` commits only tracked files, so ensure `agent.ts`, `package.json`, and `tsconfig.json` are committed/staged first (`git add`).

## 3. Add all three to the workspace

```bash
guild workspace agent add "$OWNER~confession-builder-l0"  --workspace confession
guild workspace agent add "$OWNER~confession-builder-l1"  --workspace confession
guild workspace agent add "$OWNER~confession-auditor"     --workspace confession
```

## 4. Verify (the judge-visible dump)

```bash
guild workspace agent list --workspace "$OWNER/confession" --json
guild session list        --workspace "$OWNER/confession" --limit 15 --json
```

The session list is CONFESSION's audit trail: every Builder run and every tier change is a real Guild session with token accounting. Pin the starting tier before every demo run — Guild workspace/tier state can reset.

## Tier grant, in one line

The three packages differ **only** in their tool grant:

| Agent | Tools granted | Can write? |
|---|---|---|
| `confession-builder-l0` | `github_issues_get/list/list_comments`, `github_repos_get_content`, `guild_get_me` | No — physically cannot |
| `confession-builder-l1` | L0 + `github_repos_create_or_update_file_contents`, `github_pulls_create`, `github_issues_create_comment`, `github_issues_add_labels` | Yes |
| `confession-auditor` | `github_issues_get`, `github_repos_get_content`, `guild_get_me` | No — and holds no tier-change tool |

Promotion/demotion between L0 and L1 is a real Guild tool-grant change made only by the engine's verdict handler — never a prompt edit, never a human click.

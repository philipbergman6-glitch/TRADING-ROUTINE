# Cloud routine + repo slash commands after a git sync

**Ticket:** [#70](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/70)  
**Parent map:** [#69](https://github.com/philipbergman6-glitch/TRADING-ROUTINE/issues/69)  
**Collected:** 2026-09-16  
**Sources:** code.claude.com docs fetched 2026-09-16 — [routines](https://code.claude.com/docs/en/routines), [cloud-environments](https://code.claude.com/docs/en/cloud-environments), [skills](https://code.claude.com/docs/en/skills); [CHANGELOG.md](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md) (head = 2.1.273); repo git history.  
**Scope:** facts only. No product decisions. No live trigger was read or changed; no test trigger was run.

Labels: **observed** = quoted from a primary doc or seen in repo/git. **inferred** = reasoning from observed facts. **unknown** = not documented and not tested.

---

## Gist

1. Repo `.claude/commands/*.md` are cloned into cloud runs and are valid `/name` commands (observed). The run clones the default branch fresh each time (observed).
2. The docs do not say whether a `.claude/commands/` file changed mid-session is re-read. Live reload is documented for `.claude/skills/` only, and the docs state `commands/` is *not* watched for `--add-dir` dirs (observed). Whether `/midday` would use the post-sync file is **unknown**.
3. "Read and follow `.claude/commands/midday.md`" does not depend on how commands load, so it avoids the unknown (inferred). Env vars are copied once at session start, there are no approval prompts, and user `~/.claude` config does not carry over (observed).

---

## Q1 — Are repo `.claude/commands` / `.claude/skills` loaded in cloud runs?

| # | Finding | Label | Source |
|---|---|---|---|
| 1.1 | Table "What carries over from your setup": "Your repo's `.claude/skills/`, `.claude/agents/`, `.claude/commands/` — Yes — Part of the clone" | observed | cloud-environments § What carries over |
| 1.2 | "The session can run shell commands, use [skills] committed to the cloned repository, and call any connectors you include." | observed | routines § (intro, line ~51) |
| 1.3 | "Custom commands have been merged into skills. A file at `.claude/commands/deploy.md` and a skill at `.claude/skills/deploy/SKILL.md` both create `/deploy` and work the same way." | observed | skills § top note |
| 1.4 | Repo has `.claude/commands/{midday,market-open,pre-market,daily-summary,weekly-review,...}.md`, no `.claude/skills/`, no committed `.claude/settings.json` | observed | `git ls-files .claude` |
| 1.5 | So `/midday` exists as a command in a cloud run of this repo | inferred (1.1 + 1.3 + 1.4) | — |
| 1.6 | A prompt of the form "git fetch … then run /midday": the docs describe `/name` as something "you type". They do not say whether a `/midday` in the middle of a routine prompt is expanded as a command, or is just text that Claude acts on by calling the Skill tool | unknown | skills § "invoke one directly with `/skill-name`" |

## Q2 — When are commands discovered? Is a synced file stale?

| # | Finding | Label | Source |
|---|---|---|---|
| 2.1 | "Claude Code watches skill directories for file changes … When you add, edit, or remove a skill under `~/.claude/skills/`, the project `.claude/skills/`, or a `.claude/skills/` inside an `--add-dir` directory, Claude Code picks up the change within the current session, without a restart." | observed | skills § Live change detection |
| 2.2 | "Live change detection covers `SKILL.md` text only." | observed | skills § Live change detection |
| 2.3 | "It doesn't watch the added directory's `.claude/commands/` or `.claude/agents/`, so restart the session after changing a file there." (said of `--add-dir` directories) | observed | skills § (line ~153) |
| 2.4 | Changelog 2.1.0: "skills created or modified in `~/.claude/skills` or `.claude/skills` are now immediately available without restarting the session". 2.1.152: "Added `/reload-skills` command to re-scan skill directories". Neither mentions `.claude/commands`. | observed | CHANGELOG 2.1.0, 2.1.152 |
| 2.5 | The docs never say whether the project's own `.claude/commands/` is watched. Taken together, 2.1–2.4 suggest it is **not** watched and is scanned at session start | inferred (moderate) | — |
| 2.6 | Once a skill is invoked, "the rendered `SKILL.md` content enters the conversation … Claude Code does not re-read the skill file on later turns." The docs do not say whether invocation reads the file from disk at that moment or uses a copy cached at startup | observed (first part) / unknown (read-at-invoke vs cached) | skills § Skill content lifecycle |
| 2.7 | Net effect: whether `/midday` run after `git reset --hard FETCH_HEAD` uses the pre-sync or post-sync `midday.md` is not documented. A test trigger would settle it; none was run | unknown | — |
| 2.8 | "Read and follow `.claude/commands/midday.md`" makes Claude read the file with a normal file read after the sync, so it always gets the current disk content. It does not depend on command loading | inferred (high) | — |
| 2.9 | How much the sync matters: each run is already a fresh clone of the default branch (Q3.1), so pre- and post-sync only differ if commits land on `main` between clone time and the sync. With 5 runs/day plus manual merges this can happen, but the window is small | inferred | — |

## Q3 — Branch, freshness, push rights

| # | Finding | Label | Source |
|---|---|---|---|
| 3.1 | "Each repository you add is cloned on every run. Claude starts from the repository's default branch unless your prompt specifies otherwise." | observed | routines § Repositories and branch permissions |
| 3.2 | "Cloud sessions start from a fresh clone of your repository. Anything you commit to the repo is available." | observed | cloud-environments § What carries over |
| 3.3 | "Claude pushes its work to branches prefixed with `claude/`, which are always accepted. When your prompt directs Claude to push to another branch, Claude Code checks the push first and rejects it if … the branch is protected on GitHub · someone else has an open pull request from that branch · the branch carries commits authored by someone other than you" | observed | routines § Repositories and branch permissions |
| 3.4 | Cloud runs do push straight to `main` in practice, e.g. `7057aa6 Claude <noreply@anthropic.com> midday scan 2026-09-16`. The remote also has 78 `claude/*` branches | observed | `git log origin/main`, `git branch -r` |

## Q4 — Env vars, permissions, settings

| # | Finding | Label | Source |
|---|---|---|---|
| 4.1 | "Each session copies the environment's values once, at startup, into ordinary environment variables that any command Claude runs can read. Because running sessions don't re-read the configuration, editing or adding variables affects sessions you start afterward" | observed | cloud-environments § Set environment variables |
| 4.2 | On Pro/Max, API keys can be added as "API credentials" that "the agent proxy attaches … to requests for the hosts you list"; "any key on a Team or Enterprise plan, stays in an environment variable" | observed | cloud-environments § What carries over |
| 4.3 | "there is no permission-mode picker and no approval prompts during a run" | observed | routines |
| 4.4 | Connectors: "Claude can use every tool from an included connector, including writes, without asking for permission during a run." | observed | routines § Create a routine |
| 4.5 | Carries over: repo `CLAUDE.md`, "`.claude/settings.json` hooks", `.mcp.json`, `.claude/rules/`, plugins declared in `.claude/settings.json`, server-managed settings. Does not carry over: user `~/.claude/CLAUDE.md`, `~/.claude/{skills,agents,commands}`, user-only plugins, local/user-scope MCP; transport vars in the settings `env` block are ignored | observed | cloud-environments § What carries over |
| 4.6 | The table covers `.claude/settings.json` *hooks* and plugins only. It does not say whether `permissions` or other `env` keys in `.claude/settings.json` apply in a routine | unknown | — |
| 4.7 | `.claude/settings.local.json` is gitignored here (`~/.config/git/ignore:1`), so it never reaches the clone. The repo has no committed `.claude/settings.json` | observed | `git check-ignore -v` |
| 4.8 | Whether the "no approval prompts" run corresponds to a named mode (`dontAsk` / `bypassPermissions`) is not documented | unknown | — |

---

## Open unknowns (a test trigger could settle these)

- 1.6 — whether a mid-prompt `/midday` is expanded as a command or treated as text.
- 2.6 / 2.7 — whether invoking `/midday` reads `.claude/commands/midday.md` from disk at invoke time (so post-sync) or uses a copy from session start.
- 4.6 — whether `.claude/settings.json` `permissions` / `env` apply in routines.

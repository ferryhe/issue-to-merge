# Issue to Merge

[![Validate](https://github.com/ferryhe/issue-to-merge/actions/workflows/validate.yml/badge.svg)](https://github.com/ferryhe/issue-to-merge/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Turn named GitHub Issues into reviewed, merged PRs with an evidence-backed, bounded multi-agent workflow.

`issue-to-merge` is a Codex skill for users who want more than an open-ended coding loop. It gives every Issue a fresh branch, worktree, manager, and implementation worker; runs up to fifteen script-enforced review rounds; publishes a Draft PR; handles one bounded remote-feedback window; verifies the merge closed the Issue; and cleans up before starting the next Issue.

## What it enforces

- One Issue at a time, always from the latest remote default branch.
- Fresh manager and implementation agents for every Issue.
- TDD for behavior changes and focused plus repository-required tests.
- Fresh read-only reviewer for every local review round, capped at fifteen.
- Draft PR before Ready for review, with an exact `Closes #<issue>` reference.
- One ten-minute remote-feedback window covering checks, reviews, threads, comments, and Copilot feedback.
- No branch-protection bypass and no merge while a valid blocker remains.
- Verified Issue closure and ordered branch/worktree cleanup.
- A deterministic JSON state machine in `scripts/review_cycle.py` that rejects invalid lifecycle transitions.

Issue bodies, PR text, and comments are treated as untrusted repository content. They cannot expand permissions or override user and repository policy.

## Requirements

- Codex with subagent/collaboration support.
- Git and an authenticated GitHub integration or `gh` CLI.
- Permission to create branches and PRs and, when explicitly authorized, merge them.
- A repository with an identifiable default branch and its own tests or validation commands.

The optional `$karpathy-guidelines` skill strengthens worker behavior when installed. It is not required: this skill embeds the essential simplicity, surgical-change, TDD, and evidence rules.

## Install

Ask Codex to install it from GitHub:

```text
$skill-installer install the issue-to-merge skill from https://github.com/ferryhe/issue-to-merge
```

Or clone it into the user skill directory described by the official Codex skill documentation:

```bash
mkdir -p "$HOME/.agents/skills"
git clone https://github.com/ferryhe/issue-to-merge.git "$HOME/.agents/skills/issue-to-merge"
```

Codex normally detects a newly installed skill automatically. Restart Codex if it does not appear.

## Use

Explicitly name the Issues and authorize the merge lifecycle:

```text
Use $issue-to-merge to resolve Issues #123 and #127 in order, taking each through merge and cleanup.
```

The skill intentionally does not activate for advisory questions such as “What should we do about #123?” Publishing, merging, deletion, and cleanup remain limited to the named Issues and repository.

## State helper

The manager records each lifecycle transition in a JSON state file kept outside the target checkout:

```bash
python scripts/review_cycle.py --help
python scripts/review_cycle.py status --state-file /path/to/issue-123.state.json
```

The helper enforces the review cap, exact Issue-closing reference, single remote-feedback fetch, current-HEAD check evidence, and cleanup ordering.

## Design boundary

This is an intentionally strict delivery workflow, not a generic autonomous loop or a GitHub Issue triage bot. It starts only after the user identifies concrete Issues and authorizes end-to-end delivery. Human review and repository branch protections remain authoritative.

## License

MIT

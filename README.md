# Issue to Merge

[English](README.md) | [简体中文](README.zh-CN.md)

[![Validate](https://github.com/ferryhe/issue-to-merge/actions/workflows/validate.yml/badge.svg)](https://github.com/ferryhe/issue-to-merge/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Turn named GitHub Issues into reviewed, merged PRs with an evidence-backed, bounded multi-agent workflow.

`issue-to-merge` is a portable [Agent Skill](https://agentskills.io) for coding-agent runtimes that support subagent delegation and GitHub operations. It gives every Issue a fresh branch, worktree, manager, and implementation worker; runs up to fifteen script-enforced review rounds; publishes a Draft PR; handles one bounded remote-feedback window; verifies the merge closed the Issue; and cleans up before starting the next Issue.

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

- An Agent Skills-compatible coding-agent runtime.
- Support for fresh subagents with distinct manager, worker, and reviewer roles.
- Git and an authenticated GitHub integration or `gh` CLI.
- Python 3.10 or newer for the lifecycle state helper.
- Permission to create branches and PRs and, when explicitly authorized, merge them.
- A repository with an identifiable default branch and its own tests or validation commands.

## Install

Clone the repository:

```shell
git clone https://github.com/ferryhe/issue-to-merge.git
```

Then register the cloned directory using your agent runtime's skill installation mechanism. The repository root is the complete skill directory: it contains `SKILL.md`, the manager prompt, and the deterministic lifecycle helper.

## Use

Explicitly name the Issues and authorize the merge lifecycle:

```text
Use the issue-to-merge skill to resolve Issues #123 and #127 in order, taking each through merge and cleanup.
```

The skill intentionally does not activate for advisory questions such as “What should we do about #123?” Publishing, merging, deletion, and cleanup remain limited to the named Issues and repository.

## State helper

The manager records each lifecycle transition in a JSON state file kept outside the target checkout:

```bash
python scripts/review_cycle.py --help
python scripts/review_cycle.py status --state-file /path/to/issue-123.state.json
```

The helper enforces the review cap, exact Issue-closing reference, single remote-feedback fetch, current-HEAD check evidence, and cleanup ordering.

## Runtime compatibility

Runtime tool names are intentionally not prescribed. Map the controller, manager, implementation worker, local reviewer, and remote-feedback worker roles to the runtime's own subagent mechanism. The runtime must preserve role isolation, provide each agent with the required context, and enforce the mutation boundaries described in `SKILL.md`.

## Design boundary

This is an intentionally strict delivery workflow, not a generic autonomous loop or a GitHub Issue triage bot. It starts only after the user identifies concrete Issues and authorizes end-to-end delivery. Human review and repository branch protections remain authoritative.

## License

MIT

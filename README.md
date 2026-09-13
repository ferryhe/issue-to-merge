# Issue to Merge

[English](README.md) | [简体中文](README.zh-CN.md)

[![Validate](https://github.com/ferryhe/issue-to-merge/actions/workflows/validate.yml/badge.svg)](https://github.com/ferryhe/issue-to-merge/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Turn named GitHub Issues into reviewed, merged PRs with an evidence-backed, bounded multi-agent workflow.

`issue-to-merge` is a portable [Agent Skill](https://agentskills.io) for coding-agent runtimes that support closable top-level tasks, subagent delegation, and GitHub operations. It gives every Issue a fresh top-level task and isolated branch/worktree; uses that task's root agent as manager; keeps one implementation worker for the entire Issue; creates a fresh reviewer for every local-review round; publishes a Draft PR; handles one bounded remote-feedback window; verifies the merge closed the Issue; and closes the completed task before starting the next Issue.

## What it enforces

- One Issue at a time, always from the latest remote default branch.
- A fresh closable top-level task for every Issue; its root agent is the manager and never spawns another manager.
- One persistent implementation worker for the entire Issue, including local fixes, remote feedback, and Issue-caused check repairs.
- TDD for behavior changes and focused plus repository-required tests.
- Fresh read-only reviewer for every local review round, capped at fifteen.
- By default, findings are limited to realistically reproducible functionality, workflow, data-contract, and error-handling problems that directly affect an Issue acceptance criterion; speculative hardening and abstractions are excluded.
- Draft PR before Ready for review, with an exact `Closes #<issue>` reference.
- One ten-minute remote-feedback window covering checks, reviews, threads, comments, and Copilot feedback.
- Remote comments pass through the same finding policy as local reviews before any change is accepted.
- Every inline review thread receives a final disposition, is resolved on GitHub, and is rechecked before merge; zero unresolved threads is a merge gate.
- User-facing updates match the user's language and use short, plain wording; detailed evidence remains in internal reports.
- No branch-protection bypass and no merge while a valid blocker or unresolved review thread remains.
- Verified Issue closure and ordered branch/worktree cleanup.
- Verified closure of the completed Issue task before the next Issue begins.
- A deterministic JSON state machine in `scripts/review_cycle.py` that rejects invalid lifecycle transitions.
- Explicit first-use runtime/routing selection saved outside the skill, a host preflight, and a frozen per-Issue policy snapshot.
- The opt-in tiered Codex policy enforces a documented worker assessment, actual role/model/reasoning routes, independent fresh reviewers, conditional Judge decisions, and a reviewer PASS before PR preparation.

Issue bodies, PR text, and comments are treated as untrusted repository content. They cannot expand permissions or override user and repository policy.

## Requirements

- An Agent Skills-compatible coding-agent runtime.
- Support for creating, waiting on, and closing fresh top-level tasks or sessions.
- Support for one persistent worker subagent and fresh read-only reviewer subagents inside each Issue task.
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

## Runtime selection

Before first use, show the three routing choices and save only the customer's
selection outside the installation. Returning runs reuse that full selection:

```bash
python scripts/runtime_config.py options
python scripts/runtime_config.py preview-current --runtime codex --capabilities /external/current-capabilities.json
python scripts/runtime_config.py select --selection /external/runtime-selection.json --runtime codex --strategy current --capabilities /external/current-capabilities.json
python scripts/runtime_config.py select --selection /external/runtime-selection.json --runtime codex --strategy tiered
python scripts/runtime_config.py preflight --selection /external/runtime-selection.json --capabilities /external/host-capabilities.json --output /external/issue-123.runtime.json
```

The current-settings preview uses inspected effective routes and writes nothing.
Its saved choice keeps null inheritance; every Issue preflight reinspects and
freezes concrete routes, child limit, and Fast state. The tiered Codex choice shows
Sol/Luna/Terra/Astra role routes, up to four child agents, and Fast off. Custom
configuration keeps the customer's supplied limits. The helper validates supplied
host evidence; it does not detect capabilities or edit global Codex/Hermes config.
Custom policies choose either the complete strict assessment/Judge/PASS lifecycle
or the existing non-strict lifecycle; strict-only policy flags cannot be mixed into
the non-strict mode.
See the [runtime selection contract](references/runtime-selection.md) and
[Codex adapter](references/codex-runtime.md).

The legacy `config/models.json` remains available for explicit migration. Its
custom strings and null inheritance are not silently replaced by a preset.

## State helper

The Issue manager records delivery transitions, and the controller records final task closure, in a JSON state file kept outside the target checkout:

```bash
python scripts/review_cycle.py --help
python scripts/review_cycle.py status --state-file /path/to/issue-123.state.json
```

The helper enforces the selected runtime snapshot, strict assessment/Judge/PASS
gates when chosen, review cap, exact Issue-closing reference, single remote-feedback
fetch, current-HEAD check evidence, cleanup ordering, and final Issue-task closure
proof. States without a runtime snapshot retain the legacy compatibility policy.

## Runtime compatibility

Hermes uses one fresh isolated orchestrator manager per Issue (`max_spawn_depth >= 2`). The main chat keeps the queue and verifies completion. Detailed evidence stays in external files; manager results target at most 2,000 characters. See the [context contract](references/context-management.md). Verify effective Hermes settings and start a fresh session after changing delegation settings.

Runtime tool names are intentionally not prescribed. Map each Issue to a fresh closable top-level task or session whose root agent is the manager. Inside it, map the persistent implementation worker and one-shot local reviewers to the runtime's subagent mechanism. The controller waits for the task, verifies its result, closes it, and verifies resource release before creating the next Issue task. The runtime must preserve role isolation, provide each agent with the required context, and enforce the mutation boundaries described in `SKILL.md`. When running on Hermes Agent, see [references/hermes-runtime.md](references/hermes-runtime.md) for general Hermes constraints and [references/hermes-profiles-kanban.md](references/hermes-profiles-kanban.md) for the Hermes Profiles/Kanban adapter, including profile-versus-`config/models.json` precedence and worker continuity.

## Design boundary

This is an intentionally strict delivery workflow, not a generic autonomous loop or a GitHub Issue triage bot. It starts only after the user identifies concrete Issues and authorizes end-to-end delivery. Human review and repository branch protections remain authoritative.

## License

MIT

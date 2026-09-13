# Issue to Merge

[English](README.md) | [简体中文](README.zh-CN.md)

[![Validate](https://github.com/ferryhe/issue-to-merge/actions/workflows/validate.yml/badge.svg)](https://github.com/ferryhe/issue-to-merge/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[v0.6.0 release notes](docs/releases/v0.6.0.md) · [runtime onboarding audit](docs/audits/runtime-onboarding-2026-09-13.md)

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

Clone the versioned release:

```shell
git clone --branch v0.6.0 --depth 1 https://github.com/ferryhe/issue-to-merge.git
```

Then register the cloned directory using your agent runtime's skill installation mechanism. The repository root is the complete skill directory: it contains `SKILL.md`, the manager prompt, and the deterministic lifecycle helper.

To track development instead, clone the default branch without `--branch`. A
version tag is recommended for repeatable installations. GitHub Releases use the
standard source archives; this project does not require a separate asset.

## Use

Explicitly name the Issues and authorize the merge lifecycle:

```text
Use the issue-to-merge skill to resolve Issues #123 and #127 in order, taking each through merge and cleanup.
```

The skill intentionally does not activate for advisory questions such as “What should we do about #123?” Publishing, merging, deletion, and cleanup remain limited to the named Issues and repository.

## Runtime selection

Before first use, show the three routing choices and save only the customer's
selection outside the installation. Start by listing the choices:

```bash
python scripts/runtime_config.py options
```

Then run exactly one selection path. For current/inherited Codex settings, first
preview inspected host evidence, then save that choice:

```bash
python scripts/runtime_config.py preview-current --runtime codex --capabilities /external/current-capabilities.json
python scripts/runtime_config.py select --selection /external/runtime-selection.json --runtime codex --strategy current --capabilities /external/current-capabilities.json
```

For the optional tiered Codex policy:

```bash
python scripts/runtime_config.py select --selection /external/runtime-selection.json --runtime codex --strategy tiered
```

For a custom configuration:

```bash
python scripts/runtime_config.py select --selection /external/runtime-selection.json --runtime codex --strategy custom --config /external/runtime-config.json
```

Every new Issue uses fresh inspected host evidence to create its frozen snapshot:

```bash
python scripts/runtime_config.py preflight --selection /external/runtime-selection.json --capabilities /external/host-capabilities.json --output /external/issue-123.runtime.json
```

Returning runs reuse the saved selection without asking again unless the customer
explicitly changes it. Preflight still inspects the host for every new Issue.

The current-settings preview uses inspected effective routes and writes nothing.
Its saved choice keeps null inheritance; every Issue preflight reinspects and
freezes concrete routes, child limit, and Fast state. The tiered Codex choice shows
Sol/Luna/Terra/Astra role routes, up to four child agents, and Fast off. Custom
configuration keeps the customer's supplied limits. The helper validates supplied
host evidence; it does not detect capabilities or edit global Codex/Hermes config.
Custom policies choose either the complete strict assessment/Judge/PASS lifecycle
or the existing non-strict lifecycle; strict-only policy flags cannot be mixed into
the non-strict mode.

The opt-in tiered Codex routes are:

| Work | Role | Model | Reasoning |
| --- | --- | --- | --- |
| Issue control | manager | gpt-5.6-sol | medium |
| Research | researcher | gpt-5.6-luna | low |
| Code exploration | explorer | gpt-5.6-luna | medium |
| Simple/normal implementation | worker | gpt-5.6-terra | medium |
| Complex implementation | senior_worker | gpt-5.6-sol | high |
| Extreme implementation | expert_worker | gpt-6-astra | high |
| Local review | reviewer / senior_reviewer | gpt-5.6-sol | high |
| Adjudication and architecture | judge / architect | gpt-6-astra | high |

Before choosing a worker tier, the manager records affected modules, coupling,
algorithm/state/migration difficulty, unresolved decisions, and the validation plan. Each
review round uses a fresh independent reviewer. A separate Judge is required after
the second and every later completed changes review, for a declared reviewer
disagreement, or for unresolved architecture/security uncertainty. Strict runs
require reviewer PASS before PR preparation; current settings and old states keep
their documented legacy behavior.

See the [runtime selection contract](references/runtime-selection.md) and
[Codex adapter](references/codex-runtime.md).

The legacy `config/models.json` remains available for explicit migration. Its
custom strings and null inheritance are not silently replaced by a preset.

## Upgrade from v0.5.0

Back up the complete old installation and local edits before replacing it,
especially a customized `config/models.json`. Preserve external selections and
Issue state files, then move a clean clone to the release tag:

```shell
git fetch --tags origin
git checkout v0.6.0
```

Selections created by v0.6.0 are stored outside the installation and target
repository, so later package upgrades preserve them. On the first v0.6.0 run,
review any v0.5.0 `config/models.json` mappings and migrate them explicitly instead
of silently replacing them. Run the new helper from v0.6.0, but point `--legacy`
at the backed-up old file:

```shell
python scripts/runtime_config.py migrate-legacy --legacy /backup/v0.5.0/config/models.json --runtime codex --output /external/migrated-runtime.json
python scripts/runtime_config.py select --selection /external/runtime-selection.json --runtime codex --strategy custom --config /external/migrated-runtime.json
```

Existing state files without a runtime snapshot retain the v0.5.0-compatible
legacy lifecycle. New strict assessment/Judge/PASS gates apply only to a newly
selected strict policy with a ready host-validated snapshot. See the
[v0.6.0 release notes](docs/releases/v0.6.0.md) for the full upgrade boundary.

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

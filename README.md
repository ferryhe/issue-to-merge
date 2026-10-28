# Issue to Merge

[English](README.md) | [简体中文](README.zh-CN.md)

Take named GitHub Issues through implementation, review, PR, merge, and cleanup. Each Issue gets a fresh runtime-defined context and worktree, with one persistent implementation worker.

## Install and prepare

Install the complete directory containing `SKILL.md` into your runtime's skill directory. In Codex, `$skill-installer` can install this repository.

- Python 3.10+, Git, and an authenticated GitHub integration or `gh`.
- The target repository's test commands and authorization for the Issue's commits, PR, merge, and cleanup.
- Selecting the TypeSafe Judge route requires `TYPESAFE_API_KEY` and enables its per-review assessments. Keep credentials out of prompts and repositories.

A development checkout and an installed skill are separate copies. Editing one does not update the other. Update skill files and references together; preserve external user configuration and Issue state.

## Use

Full mode, the default:

```text
$issue-to-merge Resolve owner/repo #123 and #127 in order, including implementation, commits, PRs, merge, and cleanup.
```

Quick mode:

```text
$issue-to-merge quick mode: owner/repo #123, including implementation, commits, PR, merge, and cleanup.
```

| Option | Behavior |
| --- | --- |
| `full`, default | Independently review each local fix until PASS or the review cap. |
| `quick` | At least one independent review; review later fixes only when behavior or a data contract changes materially. |
| `Copilot auto`, default | Request review when available; record unavailability or timeout and disable it for this Issue. |
| `Copilot off` | Do not request or wait for Copilot. Still assess other feedback and current-HEAD CI. |

Copilot and delivery mode are independent options. Add “Copilot off” to either example. Both modes request Copilot only once, during initial PR publication. Later fixes and pushes never request it again; keep the original feedback snapshot and run required local review and fresh CI.

Both modes keep local review, the configured Judge, CI, and branch protection; TypeSafe assessments apply when that provider is selected. At the review cap, complete required adjudication and the final tested fix, then commit without another local review or a fabricated reviewer PASS. Remote comments pass through the same finding policy as local findings; zero unresolved threads is a merge gate.

## Model configuration

Delivery mode and implementation complexity are separate choices. `full/quick` chooses the review flow; `simple/normal/complex/extreme` chooses the worker route. See the [model configuration guide](references/model-configuration.md) and [Codex JSON](config/runtimes/codex.json). User and project choices take precedence. Keep the selected worker for the entire Issue.

## Runtime compatibility

Use the adapter and configuration shipped together: [Codex](references/codex-runtime.md), [Hermes](references/hermes-runtime.md) with its [profile guide](references/hermes-profiles-kanban.md). Do not mix commands or JSON schemas from different versions. Codex uses a separate top-level task. Verify inactive children and the runtime's terminal Issue state before advancing.

Advanced configuration and context rules are in the [runtime selection guide](references/runtime-selection.md) and [context guide](references/context-management.md).

## Are hooks required?

No. Explicit skill invocation starts the workflow; the state helper and CI enforce its checks. No additional Stop, pre-commit, or pre-push hook is required.

## Design boundary

Advisory questions, review-only requests, and unauthorized Issues do not start end-to-end delivery. Keep state outside the target checkout. See `python scripts/review_cycle.py --help` for commands.

Detailed rules: [SKILL.md](SKILL.md), [quick mode](references/quick-mode.md), [Copilot options](references/copilot.md).

Release preparation and upgrade notes: [v0.8.0](docs/releases/v0.8.0.md).

MIT License.

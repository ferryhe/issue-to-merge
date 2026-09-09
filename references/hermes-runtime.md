# Hermes Runtime Adapter

Use this adapter only on Hermes Agent. Read [hermes-profiles-kanban.md](hermes-profiles-kanban.md) for profile routing, durable worker continuity, and the state-script identity gates before starting an Issue.

## Isolated Issue manager

The main chat is the queue controller only. For each Issue it creates one fresh `delegate_task` manager with `role="orchestrator"`, the configured manager profile/model, and the filled Issue manager prompt. That manager delegates the persistent worker and fresh reviewers as leaf children. Code, diffs, tests, reports, and PR lifecycle work belong in its isolated context. Never flatten these duties into the main chat or create a second manager inside the Issue manager.

Before dispatch, inspect the active session's delegation schema and effective configuration. Require orchestrator children, nesting enabled, and a spawn depth of at least 2. The corresponding Hermes installation settings are:

```yaml
delegation:
  orchestrator_enabled: true
  max_spawn_depth: 2
  child_timeout_seconds: 0
```

These documented settings do not configure Hermes or prove the running session supports them. These are installation prerequisites, not permission to rewrite global settings during delivery. Start a fresh session after changing delegation settings. If nesting is unavailable, stop before Issue work and report the capability gap; do not fall back to the root acting as manager.

Pass only the exact Issue assignment, authorization, runtime/skill paths, branch/worktree/baseline, evidence-directory and state-file paths, and concise duplicate-search metadata. Do not paste conversation history or previous Issue reports. Follow [context-management.md](context-management.md) for evidence files and compact results.

## Profiles, continuity, and workspace

Resolve the manager profile/model before dispatch using the profile precedence in
[hermes-profiles-kanban.md](hermes-profiles-kanban.md). Preserve the selected worker
identity/profile/provider/model for the whole Issue. Hermes Kanban may re-dispatch
that same durable worker task as a fresh run; require its complete durable task
context and evidence paths, as the continuity contract specifies. Do not claim
exact LLM-session continuity or assume another `delegate_task` call resumes a
finished child. Preflight manager continuation through its durable Issue assignment
if a decision is needed; if unavailable, report the gap instead of moving its work
into the main chat.

Every child must use the assigned Issue worktree. Check effective isolation
settings so automatic child worktrees do not redirect edits away from that branch.
Workers retain edit/test-only permissions regardless of runtime defaults. The
worker and reviewers must not delegate further. Reviewers may write their
designated evidence report outside the checkout but may not edit project files.

## Delegate timeout

`child_timeout_seconds: 0` removes the child wall-clock cap; it does not disable failure detection, iteration limits, or cancellation. An explicit installation cap must cover a manager's whole Issue lifecycle, including the mandatory 10-minute remote-feedback wait. Keep assignments self-contained:

- provide exact file paths and ownership;
- provide the exact required change and non-goals; and
- provide focused validation commands and expected evidence.

If a reviewer fails before a usable report, record `abort-review`. A manager timeout or failure leaves the Issue incomplete and the queue stopped.

## Waiting and completion

Wait through the active runtime's completion mechanism. Where top-level delegation returns a background handle, retain it and yield for completion. Do not repeatedly poll transcripts or replay completed results. A supported controller heartbeat reads compact status only; otherwise record the limitation and use runtime progress notifications plus completion/error updates.

The manager collects command results and verifies that no child turn or Issue-owned background command remains running before returning. It stores the detailed report outside the checkout and returns the structured result, targeting at most 2,000 characters, described in the context contract. Blocked and failed results include the decision needed and evidence path.

Root verification uses selected state fields, GitHub merge/Issue/check metadata, exact branch/worktree existence checks, and runtime completion status. Check manager termination and inactive-descendant evidence before `mark-task-closed`; unknown status is not proof of completion. Do not load child transcripts, full reports, or test logs for routine monitoring.

## Compression settings

Context isolation is the workflow fix; compression is a separate installation setting. Inspect effective `compression.proactive_prune_tokens`, `compression.threshold_tokens`, and `compression.protect_last_n` using the installed version's semantics. Enable pruning at a positive token budget and choose a later compression trigger with room below the smallest context window used by the profiles. Do not rely only on a percentage of a very large model window. Preserve recent turns (the investigated installation used `protect_last_n: 12`) and save evidence before pruning. Do not copy redacted values or claim that updating the skill applied global cleanup settings.

Runtime references: [Hermes delegation documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/delegation/) and [configuration defaults](https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/config_defaults.py). Check the installed version when its exposed capabilities differ.

## State script during self-modification

When the Issue adds a new command to `scripts/review_cycle.py`, the main checkout's older script does not yet contain it. Until merge, run the new command from the Issue worktree's copy of the script.

## Command pipelines

Do not pipe one Python interpreter invocation into another. Hermes may require approval for that shape and an approval timeout can block the workflow. Run the state command directly, then inspect or filter its output separately.

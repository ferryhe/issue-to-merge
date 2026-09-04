# Hermes Runtime Adaptation

`issue-to-merge` is runtime-agnostic, but running it on the Hermes Agent runtime
surfaces a few Hermes-specific constraints. This document records the adaptations
that made an end-to-end delivery succeed on Hermes, so the next run does not have
to rediscover them.

## 1. Flatten the role hierarchy

Hermes defaults `max_spawn_depth: 1`, which is a flat topology. Current Hermes
docs also say higher configured depth can permit orchestrator nesting. This
skill does not use that flexibility. The skill's three-layer structure
(controller → manager → worker/reviewer) therefore still cannot map one-to-one
onto Hermes as authorization to add more roles.

Adaptation:

- The root controller doubles as the Issue manager. It performs the manager's
  duties directly instead of delegating them to a dedicated manager subagent.
- The controller uses `delegate_task` directly to dispatch the one implementation
  worker and each fresh reviewer as leaf agents.
- The worker and reviewers must not delegate further. Any sub-work they would
  otherwise hand off is done inline by the leaf agent itself.
- A larger configured spawn depth is not permission to add scout, audit,
  remote-only, or escalation roles. The skill topology stays root manager + one
  leaf worker + fresh leaf reviewers only.

## 2. Respect the delegate timeout

Hermes currently documents `delegation.child_timeout_seconds` with a default of
`0`, which means no wall-clock cap. A positive value imposes a hard cap on the
child run. Older or local installs may still behave differently, including
legacy deployments that effectively timed out around 600 seconds. Every task
delegated to a worker or reviewer must therefore still be self-contained and
bounded:

- Give the exact file paths to read and change.
- Give the exact change scope — what to modify and, just as important, what not
  to touch.
- Give the exact validation command to run, so the leaf agent can prove its work
  without wandering.

A vague or open-ended task is the main cause of subagent timeouts on Hermes.

For the Hermes Profiles/Kanban adapter used by this skill, see
[references/hermes-profiles-kanban.md](references/hermes-profiles-kanban.md).

## 3. Use the worktree's state script when bootstrapping a new command

When the Issue itself adds a new command to `scripts/review_cycle.py` (for example,
Issue #6 added `record-decision`), the main checkout's copy of the script does not
yet have that command. Running the new command against the main checkout's older
script fails.

Adaptation: run the new command from the worktree's own copy of the script
(`<worktree>/scripts/review_cycle.py`), never from the main checkout, until the
change is merged.

## 4. Avoid `python3 | python3` pipelines

On Hermes, a pipeline of the form `python3 ... | python3 ...` is flagged by the
security scanner and requires approval; an approval that times out blocks the
entire command. When running the state script, do not pipe its output into another
interpreter.

Adaptation: run the command directly, and filter or inspect the result with
`grep` or `read_file` instead of a second `python3` process.

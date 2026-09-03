# Hermes Runtime Adaptation

`issue-to-merge` is runtime-agnostic, but running it on the Hermes Agent runtime
surfaces a few Hermes-specific constraints. This document records the adaptations
that made an end-to-end delivery succeed on Hermes, so the next run does not have
to rediscover them.

## 1. Flatten the role hierarchy

Hermes' `delegate_task` does not support nesting: subagents are leaf agents and
cannot delegate further. The skill's three-layer structure (controller → manager →
worker/reviewer) therefore cannot map one-to-one.

Adaptation:

- The root controller doubles as the Issue manager. It performs the manager's
  duties directly instead of delegating them to a dedicated manager subagent.
- The controller uses `delegate_task` directly to dispatch the one implementation
  worker and each fresh reviewer as leaf agents.
- The worker and reviewers must not delegate further. Any sub-work they would
  otherwise hand off is done inline by the leaf agent itself.

## 2. Respect the delegate timeout

`delegate_task` times out after roughly 600 seconds. A worker or reviewer that
exceeds this budget fails, and the controller has to take over and recover the
work. Every task delegated to a worker or reviewer must therefore be
self-contained and bounded:

- Give the exact file paths to read and change.
- Give the exact change scope — what to modify and, just as important, what not
  to touch.
- Give the exact validation command to run, so the leaf agent can prove its work
  without wandering.

A vague or open-ended task is the main cause of subagent timeouts on Hermes.

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

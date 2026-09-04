# Hermes Profiles/Kanban Adapter

This adapter is the Hermes-specific way to execute `issue-to-merge` without
changing the skill's delivery contract. It uses Hermes Profiles for durable role
configuration and Hermes Kanban for durable dispatch, while leaving manager-owned
Git/GitHub actions and cleanup order unchanged.

## Version gate

These rules are grounded in the Hermes documentation cached on 2026-09-04:

- Profiles own config/provider/model/tools/skills/memory/sessions.
- Kanban routes implementation-follow-up work back to the original implementer
  profile, but each dispatch is a new run.
- Delegation currently defaults `child_timeout_seconds: 0`; positive values add
  a wall-clock cap.
- `max_spawn_depth` defaults to a flat topology and does not create extra roles.

If a local Hermes install behaves differently, stop and verify the installed
version before approximating this adapter.

## Portable roles vs Hermes profile names

The skill's portable role names remain:

- `manager`
- `worker`
- `reviewer`
- `remote_worker`

Those are not profile names. They are logical roles used by `config/models.json`
and the workflow text. Hermes profile names are deployment-specific strings such
as `issue-manager`, `issue-worker`, or `issue-reviewer`. The adapter must
distinguish the two:

- resolve the portable role first;
- then select the Hermes profile that will execute it; and
- record the selected profile as evidence, not the example role label.

`remote_worker` is not a fourth Hermes fleet member. On Hermes it is the same
implementation worker lifecycle returning through the same selected worker
profile.

## Continuity contract

The supported continuity contract is `worker_identity_profile`.

Record one logical worker before implementation begins:

- `worker_id`: the same durable card/task handle for this Issue on Hermes. Use
  the Kanban task id or another runtime-stable worker handle, not a one-turn run
  id.
- `worker_profile`: the exact Hermes profile name selected for that worker.
- `worker_provider` and `worker_model`: the resolved non-secret route carried by
  that profile for this Issue. Record them once and keep them immutable.
- `complete durable task context`: the full Issue context the next fresh Hermes
  run must read before acting.

That contract must remain unchanged for:

- implementation;
- local-review fixes;
- remote-feedback assessment;
- remote-feedback fixes; and
- Issue-caused required-check repairs.

On every Hermes re-dispatch, the same durable card/task handle and same worker
profile are necessary but not sufficient. The task must also carry complete
durable task context for the next run. Concretely, the Kanban task
body/comment/run history must preserve the complete Issue, acceptance criteria,
current diff/test evidence, accepted findings/fix evidence, and remote/check
evidence needed by the next run. The fresh run must read that durable context
before acting, for example through `kanban_show`.

Exact session continuity is unsupported on Hermes because Kanban hands work back
to the same profile as a fresh run. Treating a fresh run as an equivalent exact
session would be false. This is logical continuity, not exact LLM-session
continuation. If complete durable task context cannot be guaranteed, or if a
workflow requires exact session continuity, fail closed instead of approximating
it.

## Profile routing and model precedence

The selected profile is authoritative. Hermes profiles own config/provider/model, so
the profile chosen for a role decides the base provider/model/tool/skill surface.

Apply precedence in this order:

1. Select the Hermes profile for the logical role.
2. Read `config/models.json` for an optional role-model override.
3. If the role config is `null` or missing, leave the selected profile unchanged.
4. If the role config is a string, apply it only when the adapter can bind it to
   the selected profile without provider ambiguity or incompatibility.

Safe examples:

- Worker profile `openai-worker` stays on its profile model when `worker` is
  `null`.
- Worker profile `anthropic-worker` and reviewer profile `openai-reviewer` are
  both allowed; cross-provider worker/reviewer profiles are safe because each
  selected profile carries its own provider/model.

Unsafe examples that must fail closed:

- A bare role-model override that requires guessing a provider different from
  the selected profile.
- A role-model override that conflicts with the selected profile's pinned
  provider/model contract.
- Mapping `remote_worker` to a second Hermes profile or using it to switch the
  implementation worker's profile after work has begun.

null role-model config leaves it unchanged. Ambiguous or incompatible override
must fail closed.

## Executable mapping

Use this adapter shape:

1. Keep the root Issue task/session as the manager. It owns Git, GitHub, PR
   state, required-check attribution, merge, and cleanup.
2. Immediately before dispatching the implementation worker, run
   `record-worker` and then `start-implementation` with the selected worker
   route. The state machine audits declared lifecycle order; it cannot observe arbitrary out-of-band file edits.
3. Dispatch the implementation worker through Hermes using the selected worker
   profile only after the state file records `worker_identity_profile`, the
   resolved provider/model, and the implementation-start boundary.
4. For each local review round, reserve the round in the state file with a fresh
   reviewer identity and the selected reviewer profile, then dispatch exactly one
   read-only reviewer run.
5. Route remote feedback and any Issue-caused check repair back to the same
   worker id, same worker profile, and same resolved provider/model. Before the
   new run acts, it must read the complete durable task context from the Kanban
   task body/comment/run history. Do not create a remote-only worker.
6. Keep cleanup order manager-owned: remote branch, worktree, local branch,
   refreshed default branch, then task closure proof.

The state helper commands are:

```bash
python scripts/review_cycle.py record-worker \
  --state-file /path/to/issue.state.json \
  --worker-id hermes-kanban-task-42 \
  --worker-profile issue-worker \
  --worker-provider anthropic \
  --worker-model claude-sonnet-4 \
  --continuity worker_identity_profile

python scripts/review_cycle.py start-implementation \
  --state-file /path/to/issue.state.json \
  --worker-id hermes-kanban-task-42 \
  --worker-profile issue-worker \
  --worker-provider anthropic \
  --worker-model claude-sonnet-4

python scripts/review_cycle.py start-review \
  --state-file /path/to/issue.state.json \
  --reviewer-id hermes-review-round-1 \
  --reviewer-profile issue-reviewer

python scripts/review_cycle.py record-fix \
  --state-file /path/to/issue.state.json \
  --worker-id hermes-kanban-task-42 \
  --worker-profile issue-worker \
  --worker-provider anthropic \
  --worker-model claude-sonnet-4 \
  --report fix-1.md \
  --validation "python3 -m unittest ..."

python scripts/review_cycle.py record-check-repair \
  --state-file /path/to/issue.state.json \
  --worker-id hermes-kanban-task-42 \
  --worker-profile issue-worker \
  --worker-provider anthropic \
  --worker-model claude-sonnet-4 \
  --head-sha def456 \
  --validation "targeted tests passed" \
  --evidence "Issue-caused check failure fixed on current PR HEAD"
```

## Topology limits

`max_spawn_depth` does not change the skill topology. Even if Hermes allows a
larger depth, this adapter remains:

- one manager;
- one persistent worker identity/profile; and
- one fresh reviewer per completed round.

worker/reviewer remain leaves. Extra fleet profiles are unused. Do not add
scout, audit, final-gate, remote-only, or escalation roles through Hermes
topology settings.

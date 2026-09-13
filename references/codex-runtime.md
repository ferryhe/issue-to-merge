# Codex runtime adapter

Use this adapter after the customer selects Codex routing through
[runtime-selection.md](runtime-selection.md).

Resolve and preflight the manager route before creating the Issue task. Use role
selectors where supported. Otherwise pass the exact model and reasoning from the
frozen snapshot with isolated, self-contained prompts. Record the actual route in
the Issue state; the JSON choice alone does not prove which model ran.

For current settings, inspect and preview the effective manager, worker-tier, and
reviewer model/reasoning routes, current child limit, and boolean Fast state before
saving the choice. The saved config keeps null inheritance. Repeat that inspection
for each Issue preflight; the ready snapshot binds the fresh concrete values and is
the only routing view used for child creation. Partially inherited custom routes
use the same evidence and must preserve their explicit fields.

The shipped tiered preset selects:

- manager: gpt-5.6-sol, medium;
- researcher: gpt-5.6-luna, low;
- explorer: gpt-5.6-luna, medium;
- simple/normal worker: gpt-5.6-terra, medium;
- complex worker: gpt-5.6-sol, high;
- extreme worker: gpt-6-astra, high;
- reviewer and senior reviewer: gpt-5.6-sol, high; and
- architect and Judge: gpt-6-astra, high.

It allows at most four concurrent children and requires Fast mode off. These are
properties of this opt-in preset, not defaults imposed on current/custom users.

Before selecting a worker tier, record affected modules, cross-module coupling or
state/migration difficulty, unresolved decisions and the validation plan.
record-assessment makes that evidence executable. The worker tier and actual
model/reasoning must match the frozen route. Keep that worker handle for all fixes,
remote assessment and check repairs.

Every local review uses a fresh reviewer id, fork_turns="none", the configured
Sol/high route, and no prior reviewer/Judge conclusions. A reviewer id cannot equal
the worker id or any earlier reviewer id.

The separate read-only Astra/high Judge is conditional. Request it for a declared
reviewer disagreement or in-scope architecture/security uncertainty. The second
and every later completed changes review automatically opens a pending adjudication
keyed to that completed round. Aborted attempts and check failures do not increment
this count. A resolved Judge decision clears only that decision; it does not reset
the count or create a review PASS. A blocked decision stops the affected path.

The strict preset requires a configured-reviewer PASS before PR preparation. If
the last allowed review returns changes, the Issue remains blocked; there is no
unreviewed final-fix bypass and no extra review.

Any strict custom policy also specifies concrete model and reasoning for manager,
every worker tier, reviewer, and Judge. Host preflight validates those selected
routes; it never replaces a customer's Judge with the shipped preset route.

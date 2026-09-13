# Runtime onboarding and role-routing audit

Audit date: 2026-09-13. Baseline: `6b6beecc37aeb0de9ed537ccfc857b18023af569`.

## Scope

Reviewed the lifecycle helper, configuration contracts, tests and CI, skill entrypoint,
manager runbook, English and Chinese READMEs, Codex/Hermes adapters, context isolation,
verification-only delivery, and GitHub checks and review-thread gates. Baseline
validation passed all 30 tests.

Findings below concern reproducible workflow and data-contract behavior relevant to
portable onboarding, assessed worker routing, independent review and conditional
adjudication. This is not a penetration test or a measurement of model quality.

## Findings and changes

| Area | Observed behavior | Change in this PR |
| --- | --- | --- |
| Customer choice | The baseline has nullable role-model mappings but no first-use runtime/routing selection or saved effective policy. | Present current settings, an optional tiered Codex preset, and custom configuration; save the explicit choice outside both the skill and target repository. |
| Stable reuse and migration | Model mappings alone cannot describe runtime capabilities, role effort, tier selection or lifecycle policy. | Schema-v2 configurations, explicit legacy migration, override precedence and saved full effective settings; no silent preset upgrade. |
| Assessment and adjudication | The baseline state machine cannot enforce assessed worker tiers or the requested Judge triggers. | A validated runtime snapshot freezes policy per Issue; strict runs require assessment and exact configured routes, and block affected transitions while declared adjudication is pending. |
| Review limit | Legacy round 15 permits a final unreviewed fix to close local review. | A selected strict policy requires PASS and stops at its review limit. Existing legacy states retain their documented behavior. |
| Agent independence | The baseline accepts the implementation worker's identity as a reviewer. | Reject worker/reviewer identity reuse; strict adjudication also requires an independent Judge. The new review found and corrected manager identity reuse as reviewer/Judge. |
| Merge runbook | The executable manager sequence omitted `record-review-threads`, although the state machine requires current-HEAD zero-unresolved-thread evidence. | Record that evidence before `mark-merged`; retain the actual gate. |
| Hermes preflight | During implementation review, Hermes/current could pass without nested-delegation evidence. | Every Hermes strategy must demonstrate the manager-to-child topology and depth of at least two, while preserving profile/model inheritance. |
| Current-settings evidence | Inherited null routes could bypass actual-route/Fast checks and produce a ready snapshot without a concrete preview. | Preview inspected current settings before selection, preserve saved inheritance, then resolve and validate concrete dispatch evidence for each new Issue. |
| Custom strict Judge | A strict custom config could inherit null Judge fields, pass preflight, and dead-end when adjudication was required. | Require explicit model/reasoning for strict Judge routes during configuration validation, consistently with other strict lifecycle roles. |
| Custom policy consistency | Non-strict custom settings could declare assessment, PASS or Judge requirements that their lifecycle could not enforce. | Reject those incompatible combinations during configuration validation; keep the supported strict and legacy modes distinct. |

Implementation references: [runtime selection and capability checks](../../scripts/runtime_config.py),
[state transitions](../../scripts/review_cycle.py),
[manager runbook](../../references/issue-manager-prompt.md),
[onboarding regressions](../../tests/test_runtime_onboarding.py), and
[baseline lifecycle regressions](../../tests/test_review_cycle.py).

An additional delivery risk was a stale local checkout predating recently merged
worker-continuity and unresolved-thread safeguards. This PR was built on the current
main revision above rather than replacing it with that checkout. This was a local
delivery risk, not a defect in the repository.

## Preserved behavior

The baseline already records worker identity/profile/provider/model continuity,
explicit implementation start, same-worker local/remote/check repairs, reviewer
history, one 600-second remote-feedback window, current-HEAD checks, zero unresolved
review-thread evidence, Issue closure, ordered cleanup and terminal context proof.
Those behaviors and their tests remain.

Hermes keeps profile-first resolution and durable task continuity; this does not
claim exact LLM-session continuity. Verification-only delivery still publishes
acceptance evidence through a PR. Neither a Judge decision nor local PASS replaces
GitHub checks, remote-feedback handling, or authorization to merge.

Development followed the selected assessed-worker process: a complex-tier Sol/high
worker retained implementation ownership, separate Sol/high agents reviewed each
revision, and an independent Astra/high Judge confirmed the two configuration
findings after the second completed failed review and the new policy-consistency finding after the third. The Judge's decisions were returned to
the same worker; they did not count as review PASS.

## Host and skill boundaries

Codex host configuration and a reusable skill are separate layers. This package
offers optional routes and validates inspected capability evidence. Selecting a
preset does not rewrite global Codex/Hermes settings or change an already-running
controller. Loading the skill in a chat does not establish that the runtime supports
task creation, persistent children, isolated reviewers or model selection. See the
[Codex adapter](../../references/codex-runtime.md),
[Hermes adapter](../../references/hermes-runtime.md), and
[first-use contract](../../references/runtime-selection.md).

The opted-in Codex preset selects Sol/medium for coordination, Luna for research and
exploration, Terra/medium for normal implementation, Sol/high for complex work,
Astra/high for extreme work and architecture/Judge decisions, and Sol/high for
independent reviews. It sets four child agents and Fast off. Customers can instead
choose inherited settings or an explicit custom policy.

## Recommendations and limits

1. Version routing choices. Reuse saved effective settings; present meaningful
   policy changes before an explicit reselection.
2. Inspect capabilities at dispatch. Supplied evidence and schema validation cannot
   prove the actual model, reasoning effort, service tier or isolation used by a host.
   Never silently substitute unavailable routes.
3. Keep semantic judgments with the manager and independent reviewers. The helper
   enforces declared transitions and identities; it cannot detect undeclared disputes
   or infer code quality from a PASS string.
4. Run a small real-runtime smoke scenario when upgrading Codex or Hermes. Unit and
   CLI tests do not exercise live model execution, GitHub branch protection or every
   customer's profile installation.
5. Retain legacy compatibility deliberately. Do not invent historical assessment or
   Judge evidence when reading old state. New strict runs must initialize from their
   validated snapshot.
6. Keep prior reviewer/Judge conclusions out of each fresh reviewer's context. Share
   them only with the implementation worker and the independent adjudicator when
   needed for their assigned decision.

## Validation

The 50-test suite passes, including all 30 baseline tests and 20 onboarding/lifecycle
regressions. Helper compilation, skill metadata validation and whitespace checks
pass. The synchronized installed package also passes all 50 tests; its 21 source
files were hash-compared with the checkout. Independent-review and hosted-CI
results are recorded in the PR description.

The local CLI smoke exercises first use, saved reuse, host preflight, assessment
ordering, two failed reviews, independent Judge resolution and a subsequent fresh
reviewer PASS. It verifies that adjudication itself cannot create PASS. These are
temporary state-machine scenarios, not live Issue implementations or merges.

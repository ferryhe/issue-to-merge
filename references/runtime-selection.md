# Runtime selection and onboarding

Use this contract before creating the first Issue task, branch, or state file. Runtime
detection may help present the choices, but it is not customer consent and must not
save a choice.

## First-use choice

If resolve returns setup_required, ask once in the user's language and show a short
table:

| Choice | Routing | Review policy | Limits |
| --- | --- | --- | --- |
| Current settings | Inherit the runtime's inspected current role routes or selected Hermes profiles | Existing legacy review lifecycle | Inspected current host limits |
| Tiered Codex | Manager Sol/medium; research Luna/low; exploration Luna/medium; normal worker Terra/medium; complex worker Sol/high; extreme worker Astra/high; all review Sol/high; Judge/architect Astra/high | Mandatory assessment, conditional Judge, and reviewer PASS | Up to 4 child agents; Fast off |
| Custom | The routes and reasoning in the customer's JSON config | The policy explicitly supplied in that config | Supplied concurrency/Fast values, bounded by host capability |

For Hermes, select installed profiles before saving. The shipped Hermes JSON is an
example schema; its example profile/provider/model names are not evidence that they
exist on a customer's host.

Custom policy supports two coherent modes. A strict Codex lifecycle sets
`strict_lifecycle`, `assessment_required`, and `local_pass_required` to true and
supplies the required `policy.judge` triggers. A non-strict lifecycle sets both
requirement flags to false and omits `policy.judge`. Judge lifecycle settings are
strict-only because assessment, adjudication, and mandatory PASS transitions are
implemented together. An optional `roles.judge` route is separate and may remain
in a non-strict routing config.

State the intended external selection path. Do not write to ~/.codex/config.toml,
Codex role files, Hermes global config, or any other runtime-global file. A useful
default is ~/.config/issue-to-merge/runtime-selection.json on Unix and
%LOCALAPPDATA%\\issue-to-merge\\runtime-selection.json on Windows. Keep the
selection outside the skill installation and target repository.

`options` lists choices; it is not a preview of the running host. Before saving
current settings, the runtime adapter must inspect its effective role routing and
host constraints, write capability evidence, and show the non-writing preview:

    python scripts/runtime_config.py preview-current --runtime codex --capabilities /external/current-capabilities.json
    python scripts/runtime_config.py select --selection /external/runtime-selection.json --runtime codex --strategy current --capabilities /external/current-capabilities.json

For Codex the preview shows the concrete manager, each worker tier, and reviewer
model/reasoning route, plus the current child limit and boolean Fast state. For
Hermes it shows the concrete profile/provider/model routes and child limit; Fast is
shown only when applicable. If the runtime cannot expose these values, report that
capability gap before saving or dispatching. The helper validates inspected JSON;
it does not discover host settings or prove that a customer viewed the preview.

Also inspect the shipped config/models.json before the customer chooses. If it
contains non-null mappings, offer explicit migration:

    python scripts/runtime_config.py migrate-legacy --legacy config/models.json --runtime codex --output /path/to/candidate.json
    python scripts/runtime_config.py select --selection /external/runtime-selection.json --runtime codex --strategy custom --config /path/to/candidate.json

Migration never edits the source. Empty legacy strings require correction. A
non-null remote_worker must equal worker, because the remote phase reuses the
implementation worker. Hermes migration also requires the selected profile config;
a bare model override that cannot bind to that profile/provider fails.

Save only after the customer selects a choice:

    python scripts/runtime_config.py options
    python scripts/runtime_config.py select --selection /external/runtime-selection.json --runtime codex --strategy tiered
    python scripts/runtime_config.py resolve --selection /external/runtime-selection.json

Returning use reads the saved full effective config. Precedence is explicit
invocation config/override > saved full selection > the originally selected preset.
Explicit JSON null means runtime inheritance and is not treated as a missing field.
For a current selection, the saved config retains those nulls and stores the
observed preview as metadata. A returning run reuses the strategy without asking
again. Each new Issue supplies fresh inspected evidence to preflight, so inheritance
can follow an updated current route without silently changing the saved preference.
Invalid saved data stops setup instead of falling back.

## Host preflight and frozen snapshot

The runtime adapter must inspect the actual host for every Issue and write a short
capability evidence JSON. The helper validates supplied evidence; it does not
auto-detect or configure the host.

    python scripts/runtime_config.py preflight --selection /external/runtime-selection.json --capabilities /external/host-capabilities.json --output /external/issue-123.runtime.json

Common evidence fields are `runtime`, a non-empty `evidence` description,
`max_children`, `persistent_worker: true`, and
`fresh_isolated_reviewers: true`. Codex evidence also contains a boolean
`fast_mode` and a `models` object mapping every available model to its supported
reasoning levels. When any selected Codex route inherits a field,
`current_routes` supplies role, model, and reasoning for manager, every worker tier,
and reviewer. Hermes evidence contains `nested_delegation: true`,
`max_spawn_depth`, an installed `profiles` map, and role/profile/provider/model in
`current_routes` for inherited routes. These fields describe inspected effective
dispatch settings, not defaults inferred from an availability catalogue.

Partial inheritance in a non-strict custom config follows the same rule. The
current route must reflect every explicit selected field; a conflicting route is
rejected rather than substituted. Strict Codex policies require explicit
model/reasoning for manager, workers, reviewer, and Judge. Custom strict policies
may choose any supported concrete Judge route; they are not forced to use the
shipped Astra route.

Pass the ready snapshot to review_cycle.py init. Preflight resolves inherited
values from the fresh evidence, validates the resulting routes, and freezes those
concrete dispatch values with the policy version, sources and validation evidence
for that Issue. The manager/worker/reviewer/Judge commands record the actual
runtime handles and routes.
Configuration cannot change a controller that is already running; if the current
controller route conflicts with the selected policy, report that limit before
creating the Issue task.

An old state or a compatibility init without a snapshot retains the legacy policy.
It does not acquire assessment, Judge or strict-PASS evidence. A newly selected
strict run must use a ready snapshot.

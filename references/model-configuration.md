# Model configuration

Use `config/runtimes/codex.json` for Codex or `config/runtimes/hermes.json` for Hermes. The JSON shipped with the current installation is the source of truth for role/model fields. User instructions and repository requirements take precedence over a preset. Do not copy a JSON file from another version without using that version's migration/selection workflow.

`full|quick` controls review frequency. It does not choose a cheaper or larger worker. Assess task complexity separately:

| Task | Route | Selection evidence |
| --- | --- | --- |
| Simple | `roles.worker.tiers.simple` | Localized change with a clear path and straightforward validation. |
| Normal | `roles.worker.tiers.normal` | Several ordinary implementation steps or workflow interactions. |
| Complex | `roles.worker.tiers.complex` | Substantial state, migration, cross-module behavior, or difficult debugging. |
| Extreme, Codex | `roles.worker.tiers.extreme` | Tightly coupled architecture or difficult algorithms with interacting invariants. |
| Queue / Issue coordination | `roles.manager` | Resolve its route before creating the Issue context. |
| Independent review | `roles.reviewer`, optionally `roles.senior_reviewer` | Fresh read-only context; never reuse the implementation worker as reviewer. |
| Design / adjudication | `roles.architect`, `roles.judge` | Architect analyzes code/design; the selected Judge adjudicates. TypeSafe assessments apply only to a frozen strict `typesafe-ai` route. |

Resolve missing evidence before selecting a worker. Keep that worker's identity and route through local fixes, remote feedback, and CI repairs. Keep reviewer and Judge choices separate from worker complexity.

To customize, copy the current installation's JSON to a user-owned location outside the skill and target checkout. Edit the relevant model and reasoning fields using that file's existing schema, then validate:

```shell
python scripts/runtime_config.py validate --runtime codex --config <CUSTOM_JSON>
```

Supply that path in the skill invocation. If the installation provides `select` and `preflight`, use its runtime-selection guide to save the custom choice and freeze each Issue's routes. Otherwise pass the validated path to the controller and manager. Configuration cannot change a controller that is already running.

`null` means only the inheritance documented by the selected runtime; it never means permission to invent another model. Verify actual host support before dispatch. Treat `TYPESAFE_API_KEY` as a credential, not a model setting. The TypeSafe route uses `jev-latest` with structured decisions; it is not a Codex child agent.

## Saving a custom route in v0.8.0

Use a user-owned copy of the schema-2 configuration, then select it explicitly:

```shell
python scripts/runtime_config.py select --selection <EXTERNAL_SELECTION_JSON> --runtime codex --strategy custom --config <CUSTOM_JSON>
```

See [runtime-selection.md](runtime-selection.md) for inspected host capabilities,
each Issue's `preflight` snapshot and upgrades. Keep saved choices outside the
package so a clean installation does not erase them. Do not rewrite an existing
customer choice when shipping a new preset.

For a TypeSafe Judge, the custom `roles.judge` entry is:

```json
{
  "role": "judge",
  "provider": "typesafe-ai",
  "model": "jev-latest",
  "reasoning": "structured",
  "read_only": true,
  "fork_turns": "none"
}
```

This selection requires `TYPESAFE_API_KEY` for host preflight and enables the
structured per-review assessments and Judge calls. Other providers keep their
own configured routes; do not pass TypeSafe-only recording commands for them.

The TypeSafe lifecycle requires `policy.strict_lifecycle: true` with its required
assessment, local-review and Judge policy fields. A non-strict config may retain
an unused Judge route, but it does not activate TypeSafe recording or Judge calls.

# Quick mode

Use only when the user selects `quick mode`; keep `full` as the default. Pass the mode to each Issue manager and record `init --mode quick`. Do not change modes midway through an Issue. Model/profile selection, worker continuity, configured review/Judge gates, acceptance mapping, CI, branch protection and cleanup still apply.

Copilot is a separate `auto|off` option. Follow [copilot.md](copilot.md); quick mode works when Copilot is off or unavailable. Off/unavailable review is never recorded as reviewer PASS or Copilot completion.

1. Create a fresh isolated Issue context/worktree from the verified remote default branch. Check equivalent work and stale bug premises. Use the selected persistent worker for the numbered acceptance criteria and required tests.
2. Get one fresh independent read-only review of the complete diff. Only when the frozen strict Judge provider is `typesafe-ai`, run and record the required TypeSafe assessment; other providers omit that service step. Validate findings against the acceptance criteria, and have the same worker fix accepted findings. Inspect the correction and validation evidence.
3. Re-review only if the fix materially changes behavior or a data contract and local rounds remain. Outputs, routing, state, key matching, reconciliation, acceptance/approval decisions and persisted/API fields count as behavior or contracts. Typo, formatting and test-only corrections normally need focused validation. Judge the actual diff, not line count; treat uncertain impact as material.
4. At the last allowed local review, complete any required configured Judge adjudication, validate and record the same worker's final unreviewed fix, then commit without another local round. Never fabricate reviewer PASS. This exception is for that final local-review fix; a later material remote/check repair needing a new local round still stops at the cap.
5. Publish a Draft PR with `Closes #<N>`, complete evidence and mark Ready. Handle optional Copilot and other feedback using `copilot.md`. Copilot is requested at most once during initial PR publication; later material fixes do not reopen its window or refresh feedback. Merge after current-HEAD CI, local review, final thread dispositions and protections pass; verify Issue closure and ordered cleanup.

## Deeper first review where false passes matter

When acceptance criteria involve keys, reconciliation, acceptance gates or approval, run concrete failure fixtures during that first review:

| Area | In-scope failure fixtures |
| --- | --- |
| Keys | Missing, duplicate or mismatched identities must not select the wrong record. |
| Reconciliation | Unmatched records, duplicate matches or conflicting values must remain visible. |
| Acceptance | Failed/missing criteria or stale evidence must not produce PASS. |
| Approval | Missing/rejected approval or approval for another version must not authorize this one. |

Save inputs, expected/actual results and criterion IDs. Bug fixes retain pre-fix failure and post-fix pass evidence. This adds evidence to the review, not an automatic extra reviewer.

## State transitions

`record-fix`, `record-remote-fix` and `record-check-repair` require `--review-impact none|material --impact-evidence <REASON>`. A published local fix also records its new `--head-sha`. `none` permits manager-validated local completion; `material` requires local review unless this is the final-review-limit fix above. All completed local rounds count toward the same cap.

A material published fix invalidates local completion, CI and thread evidence for the old HEAD. Keep the initial feedback snapshot/assessment and request history. Finish required local review and current-HEAD CI, then continue without another Copilot request or feedback window. Off/unavailable policy never clears local findings or grants a merge.

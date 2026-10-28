# Optional Copilot review

Copilot policy is independent of `full|quick` delivery mode. Default new Issues to `auto`; select `off` when the user asks. In both modes, request Copilot at most once per PR, during initial PR publication. Never re-request after fixes, commits, or pushes. Pass the selected policy to the Issue manager and record it with `init --copilot auto|off`. Do not ask again for each Issue when the user already chose a policy for the queue.

- `auto`: first inspect whether Copilot was already requested automatically for the initial PR. If so, record that existing proof instead of sending another request. Otherwise try the supported review request once. Record the accepted request with `record-copilot-request`. A denied request, missing access/tool support, exhausted quota, missed initial-publication window, or no completed review after the 600-second window may be recorded as unavailable. Record the actual reason; a missed window is a workflow limit, not a GitHub denial. Disable Copilot for the rest of this Issue and continue without another permission question, quota probe, retry, or wait. The next Issue may try again unless the user chose `off`.
- `off`: record the user choice at initialization. Do not request Copilot, inspect its quota, or wait for its window. Fetch existing non-Copilot feedback immediately and handle its valid findings.

Keep independent local review, the configured Judge and assessments (TypeSafe only when the frozen strict Judge provider is `typesafe-ai`), actual current-HEAD CI, thread dispositions, branch protection, merge authorization, and cleanup in both paths. Never record disabled/unavailable Copilot as a completed review. Follow repository thread requirements when disposing of existing Copilot comments.

## State commands

```shell
python <SCRIPT> init --state-file <STATE> --issue <N> --branch <BRANCH> --manager-id <MANAGER> --mode full|quick --copilot auto|off
python <SCRIPT> record-copilot-request --state-file <STATE> --head-sha <HEAD> --evidence <REQUEST_PROOF>
python <SCRIPT> record-copilot-unavailable --state-file <STATE> --head-sha <HEAD> --evidence <UNAVAILABLE_JSON>
python <SCRIPT> mark-feedback-fetched --state-file <STATE> --snapshot <FEEDBACK> --copilot-review-head <REQUESTED_HEAD> --copilot-review-evidence <COMPLETED_REVIEW_PROOF>
```

Include the runtime's other required identity/snapshot arguments. The final command needs Copilot completion arguments only while Copilot remains enabled. Enabled review uses the recorded 600-second window; an expired timer alone never proves completion. When Copilot is off or recorded unavailable, fetch feedback without those arguments or that wait. Required CI can take longer and still must pass on the current HEAD.

Save unavailability evidence outside the checkout, for example:

```json
{
  "pr_url": "https://github.com/owner/repo/pull/123",
  "head_sha": "current-pr-head-sha",
  "code_review_completed": false,
  "reason": "GitHub rejected the review request because the account has no quota"
}
```

Use the actual current PR, HEAD, observed failure, or elapsed-window evidence. A successful request and review IDs are not prerequisites when the request itself cannot be made. No separate user-authorization file is required for `auto` fallback. The legacy optional `--authorization` and `--snapshot` arguments remain readable for existing callers.

Both modes permit one request and one feedback snapshot. The first Ready transition retains its HEAD; once a later push changes that HEAD, a new first request is rejected too. Record the initial request before repairs/pushes; legacy states can derive the Ready HEAD from their existing history. After a material published fix, keep the initial snapshot and request history, finish any required local review, and wait for CI on the new HEAD. Do not request Copilot again or reopen its window. Off/unavailable policy never removes quick mode's local review of material changes.

Preserve history in states created before this option, including any older repeated requests. Do not add another Copilot request or fabricate completion evidence.

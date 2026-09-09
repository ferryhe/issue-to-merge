# Context and evidence boundaries

The controller reads this contract before dispatch; the manager applies it to every child prompt and result. Keep the root context proportional to the Issue queue, not to source size, review rounds, or command output.

## Ownership

- Controller: queue, dependencies, brief duplicate-work metadata, assignment, decisions requiring the user, and final independent verification.
- Issue manager: source inspection, diffs, command evidence, full worker/reviewer reports, finding decisions, checks, and PR lifecycle for one Issue.
- Worker/reviewer: assigned code and current-round evidence only. Pass evidence paths rather than reproducing large text in prompts. Fresh reviewers must not receive earlier review conclusions through history or shared report bundles.

Write complete evidence into a per-Issue directory outside the checkout, beside the state file, before returning a summary. Give every agent its exact allowed report path. A read-only reviewer may write that report but must not edit project files. Record commit/baseline SHAs, command, working directory, exit status, and output path so summaries can be checked. Retain the directory after branch/worktree cleanup. Never replace evidence with a truncated log.

Redirect verbose commands to those files and return only exit status, concise outcome, and path. Inspect targeted code ranges and relevant failing excerpts instead of repeatedly reading entire files or polling accumulated process output. Managers still inspect the complete diff and every report required by the review policy; use bounded sections when large. Do not skip checks or findings to meet a context target.

## Manager result

Return one compact structured object, targeting **at most 2,000 characters**, for completion, failure, or a decision request. Save the detailed report first. Example fields (use actual values; unavailable values are `null`):

```json
{
  "issue": 123,
  "status": "merged",
  "pr": "https://github.com/owner/repo/pull/456",
  "head_sha": "<full SHA>",
  "merge_sha": "<full SHA>",
  "checks": "passed",
  "reviews_completed": 2,
  "final_fix_unreviewed": false,
  "issue_closed": true,
  "cleanup": "verified",
  "children": "inactive",
  "manager_id": "<runtime handle>",
  "state_file": "<absolute path>",
  "evidence_dir": "<absolute path>",
  "blocker": null,
  "decision_needed": null
}
```

Use `blocked`, `failed`, or `verification_only` when appropriate; never infer completion from an absent error. Preserve blocker and decision details when shortening; move extensive explanations to the evidence file. The manager reports its children's status; only the controller can verify the manager's own terminal state after return.

The controller independently queries merge SHA, current-head required checks, Issue closure, branch/worktree cleanup, refreshed default branch, and runtime terminal state. Read selected state fields rather than dumping history or decision logs. A compact report is a claim to verify, not a replacement for those gates. If proof conflicts or is missing, request focused clarification through the same Issue context; read only the specific evidence needed to resolve that discrepancy. Do not pull all reports into the root or take over implementation/review.

Persist queue position, active manager handle, state path, and pending decision outside the conversation. After compaction, recover from those records and live status instead of replaying transcripts. Send short progress updates only when useful and avoid repeatedly returning unchanged evidence.

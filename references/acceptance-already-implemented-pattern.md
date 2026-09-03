# Acceptance Already Implemented (Verification-Only Delivery)

Some Issues describe acceptance criteria that are already satisfied by the current
implementation on the remote default branch. For those Issues the gap is
**verification**, not implementation: the correct deliverable is a verification report
proving that the existing code, scripts, and docs already meet every acceptance
criterion — not new code.

> Note: throughout this document, "the remote default branch" refers to the
> repository's actual default branch. `origin/main` is the concrete name only when the
> remote default branch is `main`; when the default branch has a different name (for
> example `master` or `trunk`), use that branch's remote ref instead.

This document defines (1) how to decide that an Issue is verification-only, and (2)
the evidence the verification report must contain. It exists to make
verification-only delivery a first-class terminal state alongside code-change
delivery, not a way to skip work.

## Judgment criteria: is this Issue verification-only?

Decide **before creating the worktree**, on the latest clean remote default branch:

1. Fetch and read the latest remote default branch. Do not reason from a stale local branch,
   an old checkout, or memory.
2. Audit the existing implementation, scripts, and documentation for every surface the
   Issue touches. Read the relevant code, run the relevant scripts, and inspect the
   docs, not just file names.
3. Translate the Issue into numbered acceptance criteria (`AC-1`, `AC-2`, ...), exactly
   as you would for a code-change Issue.
4. For each acceptance criterion, compare it one-by-one against what the current
   implementation already does. Record concrete evidence for each `AC-N`: the file,
   code path, script output, or documented behavior that satisfies it.
5. If **every** acceptance criterion is already satisfied by the existing
   implementation, the Issue is verification-only. The remaining gap is proving that
   fact, not writing code.
6. If **any** acceptance criterion is not yet satisfied, or you cannot produce
   evidence for it, the Issue is a code-change Issue. Do not classify it as
   verification-only and do not hand-wave the missing criterion.

Classification is an evidence decision, not a feeling. "It looks like it's already
there" is not enough. Each acceptance criterion must map to specific, current,
reproducible evidence on the remote default branch before the Issue qualifies as
verification-only.

## Evidence the verification report must contain

A verification-only delivery is a report, delivered as a PR, that proves the existing
implementation already satisfies every acceptance criterion. It must include, at a
minimum:

- **Per-criterion mapping** — a `AC-N → existing-implementation evidence` table.
  Every numbered acceptance criterion appears exactly once, with the specific file,
  code path, script, command output, or documented behavior that satisfies it. No
  acceptance criterion may be left unmapped or covered by a bare "already done".
- **Commit log on the remote default branch** — the relevant commits (with SHAs and
  messages) on the remote default branch that introduced or carry the satisfying
  implementation, so the evidence traces to a real, merged change rather than an
  uncommitted assumption.
- **`restore-smoke` output** (where the repository has such a restore/smoke check) —
  the actual captured output showing the restored or exercised state passes, linked
  to the acceptance criteria it verifies.
- **`release-record` entries** (where the repository keeps a release record) — the
  entries that document the behavior the Issue asks for, cited for the criteria they
  cover.
- **Baseline provenance** — the exact remote default branch SHA (and fetch time) the
  audit was performed against, so the report is reproducible against a known revision.

The report is a proof that the existing implementation satisfies the acceptance
criteria. It is **not** a justification for skipping work because the code "looks"
complete. If any acceptance criterion cannot be backed by concrete evidence on
the remote default branch, the Issue is not verification-only — stop and treat it as a
code-change Issue.

## What a verification-only delivery is not

- It is **not** a shortcut. It does not waive any acceptance criterion; it produces
  evidence for each one.
- It is **not** "looks implemented, so skip". The per-criterion mapping and cited
  evidence are mandatory, not optional.
- It is **not** a reason to drop the normal quality gates. The verification report
  itself still goes through review and must close the Issue in a PR.

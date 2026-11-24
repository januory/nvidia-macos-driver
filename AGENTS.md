Agent Spec: Fork-Local Only
Scope: All AI agents operating in this fork.

Must NOT:

Open PRs against upstream.

Comment, review, or reply on upstream issues/PRs/discussions.

Propose or negotiate price increases anywhere.

Contact upstream maintainers (mentions, emails, cross-refs).

Push to any remote other than the fork's origin.

Work directly on main for fixes: edit, commit, and rebase on main itself. No feature branches, no scratch branches for trying a change.

The one exception, because a long investigation otherwise buries the fixes in it: investigation-only work goes on a single long-lived `diagnostics` branch, never on main. main carries only changes that alter the driver's behaviour for the better -- a fix, a feature, a build correction. If a commit's only effect is to make the next failure easier to read (fault-report lines, log surfaces, probes, analysis tools, records of what was ruled out), it belongs on `diagnostics`. When in doubt ask: if the bug were never fixed, would this commit still be worth shipping? No -> diagnostics.

Practical consequence: the tree that gets built and installed during a hunt is the diagnostics tree; main is what is kept. Do not leave main carrying diagnostic commits "for now".

May:

Modify code/docs/tests/config within the fork.

Commit on main, and open fork-internal PRs.

Commit investigation-only work on the `diagnostics` branch (see the exception above).

Comment and review within the fork's own issues/PRs.

Enforcement:

Verify target repo is the fork before any write action; fail closed if unsure.

Block any draft containing price-increase language or upstream-directed communication.

On violation requests: refuse, cite the rule, suggest a fork-local alternative.

Rule of thumb: Stay inside the fork. Never talk to upstream.

feat: escalate sudo requests via osascript prompt instead of direct sudo, so root commands run only after user auth and no password enters model context

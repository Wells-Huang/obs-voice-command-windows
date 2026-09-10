# Queue bootstrap arbitration

Decision: dependency_dag_change. Confidence: high. Human input required: false.
Agent: 01a08b27-5d7e-7d93-96f3-8932a7dc8ac3.
Explicit execution: gpt-6-astra / medium, windows_arbitrator instructions.

The auto-merge enrollment timing failure is not a code failure. W11-002 already
provides full_activation CI and merge_group support on protected develop.

Approved sequence:

1. W11-002 Done; preserve its CI and matching workflow assertions.
2. External W11-009 queue activation gate: export effective rules, add merge_queue
   to ruleset 20990581, and verify the resulting effective rules. No ref mutation.
3. W11-009 code PR from develop using Luna Max. Preserve topology/Astra routing
   edits selectively; do not copy W11-005 hardening into this ticket.
4. Validate PR head checks; enqueue with expected-head protection. Capture queue
   entry, merge_group SHA/checks, actual GitHub squash SHA, and trusted push CI.
5. W11-009 Done; integrate develop into PR5 without force, preserving both sets
   of policies and W11-005 hardening. Obtain new PR/queue/post-merge evidence.
6. W11-005 Done; stop, even if W11-003/004 become eligible.

Queue parameters: SQUASH, ALLGREEN, max_entries_to_build=1,
min_entries_to_merge=1, max_entries_to_merge=1,
check_response_timeout_minutes=60, min_entries_to_merge_wait_minutes=1.
Preserve zero bypass, zero human reviews, strict required / gate from integration
15368, conversation resolution, linear history, deletion and non-fast-forward
protection. Queue enrollment is distinct from ordinary pending-only auto-merge.

W11-009 depends on W11-002 and external queue activation; W11-005 depends on
W11-002 and W11-009. Shared policy files are serialized in that order. W11-009
owns tracker/templates, queue documentation, route migration and related routing
assertions; W11-005 retains ci.yml, uv.lock and workflow-layout assertions.
repair.yml remains reserved for W11-010.

Existing user option-B and GitHub administration approvals suffice. API/auth
failures do not consume code retries. No direct merge, bypass or browser flow.

## Controller enqueue schema evidence

The controller read the GitHub GraphQL schema before any queue enrollment. The
verified `EnqueuePullRequestInput` fields are:

| Field | Schema type | Enrollment use |
| --- | --- | --- |
| `pullRequestId` | `ID!` | Identifies the intended open PR. |
| `expectedHeadOid` | `GitObjectID` | Binds enrollment to the exact PR head SHA. |
| `jump` | `Boolean` | Optional queue placement control. |
| `clientMutationId` | field present | Optional mutation correlation value. |

The controller must perform this schema check, then call
`enqueuePullRequest` with the exact distinct PR head in `expectedHeadOid`.
The worker does not enqueue, merge, push, or mutate GitHub settings. A queue
entry is not completion evidence by itself; the controller must separately
capture the PR SHA, queue entry, protected `merge_group` SHA/workflow/provider,
GitHub-created final merged `develop` SHA, and the trusted `push` `ci.yml` run
successful on that exact merged SHA.

## Activation evidence

Administration API updated ruleset 20990581 at
2026-09-10T19:54:02.997+08:00. Both ruleset detail and effective develop rules
were read back: merge_queue matches all seven approved parameters; all five
previous rule types and their parameters remain present. Bypass list empty,
current_user_can_bypass=never, required / gate integration15368 strict, zero
mandatory reviews. No ref mutation or PR enrollment was performed.

The live ruleset export is preserved at
`docs/validation/w11-009-merge-queue-ruleset.json`; its `updated_at` matches
the activation read-back timestamp and its bypass actor list is empty.

## Ticket

- Ticket ID: <!-- e.g. W11-009; one ticket per branch/worktree/PR -->
- Status: <!-- Doing | PR | Merged; only the controller may record Merged/Done -->
- Branch: `codex/w11-<ticket>-<slug>`

## Dependencies

- Depends on: <!-- ticket IDs and their Done evidence -->
- External gates: <!-- name, state, and validation artifact; use `policy_verified` only when read back -->

## Scope and acceptance evidence

- [ ] This PR changes only the ticket touch set and approved exceptions.
- [ ] Acceptance criteria are listed below with links to durable evidence.
- [ ] No secret, token, password, or unredacted credential is included in code, logs, prompts, or artifacts.

<!--
For W11-009, include all queue-policy evidence. A green PR may be eligible for
the controller-owned queue, but settings read-back, auto-merge enrollment, and
a pending queue entry are not completion evidence.
-->

- Acceptance evidence:
  - <!-- link to validation Markdown/JSON, test output, or other durable artifact -->
- Queue policy evidence (W11-009):
  - Ruleset/effective-policy artifact: <!-- link and read-back timestamp -->
  - GraphQL schema check: `EnqueuePullRequestInput` fields `pullRequestId: ID!`, `expectedHeadOid: GitObjectID`, `jump: Boolean`, `clientMutationId`
  - Queue parameters: `SQUASH`, `ALLGREEN`, build group `1`, merge group `1`, wait `1` minute, timeout `60` minutes

## Verification

- Test commands:
  ```text
  <!-- exact commands and results -->
  ```
- Manual checks:
  - [ ] <!-- exact manual/policy checks and result -->

## Merge-queue and completion evidence (controller-owned)

Record these as distinct values; do not mark the ticket `Done` from settings or
enrollment alone:

- PR number and exact PR head SHA:
- Queue entry / enqueue result:
- `merge_group` SHA:
- `merge_group` workflow run URL and check-suite/provider identity:
- GitHub-created final merged `develop` SHA:
- Trusted `push` `ci.yml` run URL/ID and `required / gate` conclusion on that exact merged SHA:

The controller must schema-check the mutation and pass the exact PR head as
`expectedHeadOid`. GitHub executes protected squash only after the merge-group
`required / gate` and all branch rules succeed. Workers do not enqueue, merge,
or push.

## Risk and rollback

- Risk:
- Rollback plan:
- Cleanup/restore evidence:

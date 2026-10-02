# Evolution review

## Read the graph and claims

Use the current review-list tool, such as `list_timeline_reviews`.
Record event IDs, candidate IDs, allowed actions, expiry, and existing resolutions.
A recommendation is a proposal. Expiry is not a factual verdict.

For each endpoint:

1. Read its full body and metadata. Check subject, scope, event dates, trust, grounding, lifecycle, and visibility.
2. Read its EVOLVES chain, such as through `memory_evolves_chain`.
3. Read direct incoming and outgoing edges, such as through `memory_neighbors`.
   Check edge direction and relation. A linear summary can hide branches.
4. Follow relevant progression paths to current successors. Read their full bodies.
   Follow available cursors and truncation signals. Report unresolved graph limits.
5. Read useful Memory Links and source records. For crystals, inspect `CRYSTALLIZED_FROM` sources.
6. Search for missing siblings or successors within the existing scope when needed.

Creation time does not prove authority. An older record can contain a later verified correction.
Validation edges do not select a current version.
`is_latest=false` does not mean false, archived, or disposable.

Build a small ledger:

`review → endpoints → paths and branches → current claims → evidence → proposed effects`

## Select the minimum change

| Meaning | Treatment |
|---|---|
| New knowledge supersedes the same claim | `replaces`; preserve the old body |
| The same knowledge gains useful detail | `enriches`; inspect resulting visibility |
| An independent source corroborates a claim | `confirms`; this is validation |
| Counter-evidence leaves a claim unresolved | `challenges`; preserve the uncertainty |
| Related but independent conditions or facets | A supported Memory Link |
| Different subjects with no useful relation | Leave unrelated; repair a mistaken edge if needed |
| Correct history already reaches current knowledge | Preserve bodies and graph; explain this in the review |

A recording error can require a correction to the current claim.
A genuine change normally requires a successor.
Do not rewrite both endpoints to manufacture agreement.
For a mixed record, preserve its unique valid claims before replacing the whole record.

## Preview graph repair

Use a semantic revision tool, such as `memory_evolves_revise`, when available.
Inspect its current decision enums and supported relations.
A pair-revision tool can support `confirms` and `challenges` without supporting `same_topic` or `enriches`.
Use the appropriate relation tool for independent links, subject to the same-Space contract.

Inspect proposed edge creation and removal, visibility, labels, and apply restrictions.
Apply the returned `plan_id` with the same pair, decision, authority, relation, and reason.
Apply only within the user's authorized scope and the endpoint's review contract.

Finish content edits and read-back before the final graph preview.
Do not change its evidence between preview and apply.
Topology can extend beyond the pair. Read the whole relevant path before adding an edge.
If a wrong edge causes a cycle, repair it separately and verify before the next preview.
Do not prepare dependent plans against the same old state.

On a stale plan or changed state, read fresh evidence and review a fresh plan.
Do not silently replace an approved plan.
After a timeout or unknown mutation outcome, read state and receipts before retrying.

## Resolve Timeline reviews

Timeline graph actions have their own confirmation contract.
Use `resolve_timeline_review` with its current preview option.
Display the exact evidence and proposed effects to the person deciding.
Apply only that person's reviewed plan with its exact `plan_id` and unchanged arguments.
An unchanged plan already approved in this session does not need another approval.
A generic request to clear the feed does not substitute for the displayed graph plan.

Inspect which endpoint the plan selects. Do not infer authority from the word `newer`.
Do not use pair revision, legacy resolution, or raw edge writes to bypass this requirement.
If the guarded operation is unavailable, report the limitation and retain the review.

If verified history is already correct, use an allowed `no_change_needed` action.
Include the actual current successor IDs and rationale.
Non-graph actions can follow the current direct-action contract without a graph preview.
`dismiss` treats a flag as noise. `custom_note_only` can leave the review pending.
Read each event's allowed actions; do not rely on a fixed type-to-action table.

## Read back

Verify direct edges, direction, relation, removed mistakes, and legitimate current branches.
Verify changed bodies and preserved historical bodies.
Read lifecycle separately from visibility.
Inspect inherited labels and the persisted Timeline action or receipt.
A remaining replacement path can still hide a node after one edge is removed.
That result does not by itself mean the repair failed.

Do not archive, delete, or confirm crystals as an automatic follow-up.

Contract sources: [EVOLVES](https://mem.nowledge.co/docs/concepts/evolves),
[Memory Links](https://mem.nowledge.co/docs/concepts/memory-links),
[revision preview](https://mem.nowledge.co/docs/api/memories/evolves/revision/preview/post),
[revision apply](https://mem.nowledge.co/docs/api/memories/evolves/revision/apply/post),
[Timeline review](https://mem.nowledge.co/docs/api/agent/feed/events/event_id/review/post).

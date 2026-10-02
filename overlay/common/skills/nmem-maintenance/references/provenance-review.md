# Provenance and candidate coverage

Read [evolution-review.md](evolution-review.md) before editing a claim or its type.
A contradiction pair and a cleanup batch are different scopes.

## Match the type to the meaning

Use the deployment's supported types and enums.
A fact records a reference claim. A learning records a durable lesson.
A decision records a choice. A plan records intent. An event records a dated outcome.
A procedure records a reusable method. Source attribution does not determine type.

Read original sources to verify speaker, subject, date, conditions, and certainty.
Do not convert an assistant's suggestion into the user's decision.
Do not invent citations, dates, or certainty to remove a provenance flag.
A source-derived fact can remain a fact with honest grounding.
An external citation does not automatically assert an interpretation.

Use a supported update tool for trust or grounding fields.
Check omitted-field and null semantics before sending a mutation.
If the client lacks a field, report that limitation.
Do not downgrade a valid fact or clear a value merely to fit the client.

## Cover the requested set

1. Enumerate each event's complete candidate set with supported pagination.
   If coverage is bounded or unknown, state that limit.
2. Deduplicate overlapping reads. Preserve membership for each event.
3. Read bodies, history, lifecycle, links, and relevant crystal sources.
4. Assign each candidate a disposition supported by evidence.
   Examples are keep, correct, follow valid history, or an explicitly scoped lifecycle change.
5. Preserve unique facts, dated outcomes, and provenance used by active crystals.
6. Close an event only after all its candidates have a reviewed disposition.

Do not close a large cleanup event because a few related pairs were resolved.
Do not treat a keyword hit as an archive decision.
Do not assume every record belongs to one abandoned topic or project.

## Verify mutation and closure

Prepare factual corrections before a graph preview that uses those bodies.
Follow the exact-plan procedure for guarded graph actions.
Read the resulting state and persisted review outcome.
A note alone does not prove closure.

For an incorrect archive, use the supported restoration workflow.
An ordinary content update might leave a memory archived.
Do not create a duplicate or claim restored recall without verification.

Sources: [memory types and CLI](https://mem.nowledge.co/docs/cli),
[lifecycle](https://mem.nowledge.co/docs/concepts/memory-lifecycle),
[review inbox](https://mem.nowledge.co/docs/api/agent/feed/events/get).

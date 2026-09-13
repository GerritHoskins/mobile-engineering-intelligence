## Review-Based Revisions (2026-09-13)

### Plan-review cleanup pass

1. **[DONE]** Clarify consistency-issue expectations for ambiguous UNKNOWN scenarios in the step plan:
   - Cases `F` and `G` are treated as `consistency_issues=[]` by default (no explicit blocker exists), with `effective_state.deliverable=UNKNOWN`.
   - This removes the prior `none/INFO` ambiguity and makes the contract testable.

2. **[DONE]** Keep scope and terminology alignment between plan and `mvp_plan.md`:
   - Preserve `intent/capability/registration` domain names and precedence model as the source of truth.
   - Keep `deliverable` tri-state logic explicit and unchanged: `FALSE > UNKNOWN > TRUE`.

3. **[DONE]** Preserve the repo-policy constraint that documentation conflicts must be surfaced rather than silently reconciled:
   - Keep the note that root path in this workspace is `mobile-engineering-intelligence/` while the doc references `mobile-eng-intelligence/`.
   - Keep this conflict explicit as a tracking item in the plan context.

4. **[DONE]** Add a local review timestamp and keep a lightweight changelog for subsequent passes.

### Prior external revisions (summary)

The following points from `context-vault` are already implemented/locked and intentionally unchanged:

1. **[DONE]** Normalize before evaluation and reject unknown raw tokens.
2. **[DONE]** Deterministic overlap handling with three-step precedence (`DISABLED` short-circuit → all-issues collection → deliverable precedence).
3. **[DONE]** Distinct contract for missing/stale/not-registered registration conditions.
4. **[DONE]** Fixed observation count to 13 (A–M) for seeded cases.
5. **[DONE]** Empty-observation response is `200` with `UNKNOWN` states and empty findings.
6. **[DONE]** Strict `subject_type=installation` in API scope.

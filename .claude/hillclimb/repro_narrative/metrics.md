# Reproduction-narrative eval: metrics

Inputs: 20 frozen evidence packets (evals/repro_narrative/cases): RP1-RP6 real, S01-S14 synthetic.

- **win** (headline): blind pairwise judge (claude-fable-5-1) vs the frozen baseline rep-0 narrative.
  1 = variant better, 0 = baseline better, 0.5 = tie or both_bad. Baseline rows are 0.5 by definition.
  A/B order randomized per (case, rep, variant); both narratives are untrusted data to the judge.
- **faults** (lower is better; non-baseline rows only): faults the judge found in the variant's narrative.
  F1 fact misattributed to a cited item; F2 a varying condition presented as required; F3 suspect stated
  as cause; F4 an UNKNOWN/gap filled in; F5 invented step or narrated "... N more steps ..." placeholder;
  F6 a missing-evidence question that closes no gap/unknown.
- **grounded**: share of sentences surviving the citation check (rejected claims count against).
- **coverage**: share of critical packet items (preconditions, gaps, failure, suspects) cited anywhere.
- **steps_in_order**: 1 if every step-* is cited in steps_prose in packet order. Vacuously 1 with no steps.
- **gaps_questioned**: 1 if every gap-* is cited by a missing-evidence question. Vacuously 1 with no gaps.

A narrative that fails schema validation or has nothing grounded scores 0 on everything (graded failure).
Truncated (max_tokens) and refused attempts are counted but not averaged. API/serving/timeout/grader
failures and fallback-served answers go to errors.jsonl and are never scored.

Caveat: on sign-off the input set was judged only *partially* representative of real traffic
("fine for now"). Treat scores as indicative until the set is extended with real meinestadt incidents.

# Experiment spec v1.1 change proposal

Status: `PROPOSED`; not executed and not a frozen experiment specification.

Run 001 of `dependency-aware-upstream-controlled-text-pilot-v1` showed that restricting numeric
candidate generation to the union of baseline/no-op BM25 top-k chunks can exclude every controlled
error. Both Boeing repairs were on p55, while the frozen top-k traces never retrieved p55. The
policies therefore compared only normal inspections.

A future v1.1 should change only after a development-only design pass:

1. Generate parse-verification candidates independently of downstream QA top-k, or define a second
   frozen candidate-retrieval mechanism with an explicit coverage budget.
2. Report candidate recall for evaluation-labeled errors after selection inputs are frozen. This is
   an evaluation diagnostic, never a policy feature.
3. Refuse to present policy-effect comparisons when no evaluation error is in the candidate
   universe; continue to report the run as a candidate-recall failure.
4. Preserve normal candidates, unit-cost charging, gold/repair separation, fresh reruns, and the
   distinction between graph overlap and actual recovery overlap.
5. Tune the new candidate route only on development documents. Run 001 and any document inspected
   while designing v1.1 cannot be reused as independent final evaluation.

This proposal does not make output-only or multi-stage allocation comparable. Those remain separate
specification tasks requiring cost and correction-unit mappings.

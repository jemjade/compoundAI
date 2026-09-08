# v1.2 Boeing interpretation correction: derivable versus unsupported values

Status: append-only interpretation amendment. The frozen v1.2 rules, raw outputs, judgments,
summary, and report remain unchanged. Boeing is closed to further model/prompt tuning and remains
development diagnostic material only.

The damaged p55 representation does not directly contain `66,608` in the `Total revenues` row.
It does, however, directly contain product sales `55,893` and service sales `10,715`, whose valid
sum is `66,608`. The earlier interpretation was too categorical where it described `66,608` as a
hallucinated or unsupported value merely because the damaged total row showed `6,608`.

The corrected evidence taxonomy is:

- Directly present: `55,893` product sales, `10,715` service sales, and the other values visibly
  present in the supplied damaged source.
- Validly derivable: `66,608 = 55,893 + 10,715`, if the output actually presents that calculation
  or an equivalently explicit derivation.
- Unsupported: a value or semantic claim that neither appears nor follows from the supplied
  evidence and shown operations.

The v1.2 damaged-table output stated `66,608`, but its shown calculation was instead
`55,893 - 53,969 = 1,924`; it did not show `55,893 + 10,715 = 66,608`. Therefore the numeric value
`66,608` is source-derivable, but the model's actual generation route is **unknown**. It must not
be labeled hallucinated solely from absence in the damaged total row, and it must not be credited
as a demonstrated calculation either.

Likewise, `1,924` is arithmetically derivable as product sales minus product cost, but labeling it
the total gross margin/profit basis is semantically unsupported because it omits the services
components. The output also did not supply the comparable FY2021 calculation needed to support
its improvement claim. This correction changes the interpretation label, not the preserved v1.2
frozen score.

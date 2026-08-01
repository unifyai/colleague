# Golden-label calibration round

This run (and its hermes counterpart `2026-07-31T16-02-27Z-hermes`) used the
first fixture revision, whose golden labels contained two genuinely
ambiguous templates (an account-lockout "blocked" item readable as bug, and
billing-discrepancy amount items readable as other). The tell: both arms —
different architectures, same underlying model — produced byte-identical
score dents at the same rounds, i.e. the systems agreed with each other and
disagreed with the golden labels. That cross-arm identity is also direct
evidence the harness treats both sides equally.

The fixture was recalibrated (amounts confined to crisply-categorized
refund templates; the lockout item reworded to an unambiguous
password-reset request) and validated to 100% agreement with the benchmark
model at both thresholds across repeated samples. The definitive runs are
the later result directories.

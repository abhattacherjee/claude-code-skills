# Vacuous tests — red flags in full

`review:deep` rejects a guard or check whose test cannot fail. The four patterns below come from
the Red Flags list in SKILL.md.

- **Accept a planted-regression test that can pass vacuously.** Every new guard/check needs a
  fail-first negative: confirm the assertion FAILS when the code is broken. A test asserting on a
  static string that's always present is the classic vacuous trap.
- **Accept a negative control that re-implements the assertion instead of invoking it.** A control
  built from the guard's own logic tests the copy, not the guard: gut the real assertion and the
  control still passes. Measured on openclaw #336 — a doc-contract test added specifically to
  prevent vacuous assertions had three controls of this shape, and three mutations each gutting a
  real assertion all SURVIVED at `5 passed`. The control must call the same function the suite
  calls, or parametrize over the same table it does.
- **Accept an "expect nothing" assertion with no positive control.** An absent-pattern fixture
  catches a guard stuck ON; only a present-pattern fixture catches one stuck OFF, where "correctly
  reports nothing" and "hardcoded empty" produce the same green. (Downstream side effects can
  sometimes tell them apart — assert on what the code was supposed to *write*, not only on what it
  reported.) Require both directions for any detector or guard, and prefer proving it by mutation —
  patch the guard to `false &&`, confirm the suite goes red — over inspection. **Fixture
  reachability is a third axis, independent of both:** a fixture that cannot reach the failing half
  yields a green assertion over an uncovered path, so check that each assertion's fixture can
  actually express the failure, not merely that the assertion exists.

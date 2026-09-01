"""Phase 7, Part 2: formal multiple-testing correction.

Phase 5's search_space.py already reports a NAIVE Bonferroni-adjusted
alpha "for context only" (it explicitly documents that raw correlation
figures in this codebase are not valid i.i.d. tests, so a correction alone
doesn't fix that). This module goes further: given a set of actual raw
p-values from one research family, it computes THREE different correction
methods and is explicit about when each is the right tool — never claims
one is universally correct.

WHEN TO USE WHICH (documented, not just asserted):
  - Bonferroni: simplest, most conservative. Controls family-wise error
    rate (FWER) — the probability of ANY false positive across the whole
    family. Appropriate when even one false discovery is costly and the
    family is not too large. Overly conservative as the family grows.
  - Holm-Bonferroni: also controls FWER, uniformly more powerful than
    plain Bonferroni (rejects at least as many hypotheses) — a strictly
    better choice than Bonferroni whenever FWER control is the goal.
  - Benjamini-Hochberg: controls the FALSE DISCOVERY RATE (FDR) — the
    expected PROPORTION of false positives among rejected hypotheses, not
    the probability of any false positive at all. Appropriate for
    exploratory research with a large family, where some false positives
    are tolerable as long as most "discoveries" are real. Less
    conservative than FWER methods, so more hypotheses survive — the
    tradeoff is a weaker guarantee.

None of these corrections fix the deeper problem this codebase already
documents everywhere else: financial return correlations are not i.i.d.,
so even a "correctly adjusted" p-value here is still approximate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class CorrectedResult:
    label: str
    raw_p_value: float
    adjusted_p_value: float
    significant_at_alpha: bool


@dataclass(frozen=True)
class MultipleTestingReport:
    method: str
    alpha: float
    n_tests: int
    results: tuple[CorrectedResult, ...]
    n_significant: int
    guidance: str

    def render(self) -> str:
        lines = [f"Multiple-testing correction: {self.method}", f"alpha={self.alpha}  n_tests={self.n_tests}  n_significant={self.n_significant}", ""]
        for r in self.results:
            lines.append(f"  [{'SIG' if r.significant_at_alpha else '   '}] {r.label}: raw_p={r.raw_p_value:.4f} adjusted_p={r.adjusted_p_value:.4f}")
        lines.append("")
        lines.append(self.guidance)
        return "\n".join(lines)


def bonferroni_correction(labeled_p_values: Sequence[tuple[str, float]], *, alpha: float = 0.05) -> MultipleTestingReport:
    """adjusted_p = min(1, raw_p * n). Controls FWER. Most conservative."""
    n = len(labeled_p_values)
    results = []
    for label, p in labeled_p_values:
        adj = min(1.0, p * n) if n > 0 else p
        results.append(CorrectedResult(label=label, raw_p_value=p, adjusted_p_value=adj, significant_at_alpha=adj < alpha))
    return MultipleTestingReport(
        method="Bonferroni (FWER control)", alpha=alpha, n_tests=n, results=tuple(results),
        n_significant=sum(1 for r in results if r.significant_at_alpha),
        guidance="Bonferroni controls the probability of ANY false positive across this family. Conservative — appropriate when a single false discovery is costly.",
    )


def holm_bonferroni_correction(labeled_p_values: Sequence[tuple[str, float]], *, alpha: float = 0.05) -> MultipleTestingReport:
    """Step-down procedure: sort ascending, compare the k-th smallest
    p-value to alpha/(n-k+1); once one comparison fails, every later
    (larger) p-value is also treated as non-significant, and the adjusted
    p-value is enforced non-decreasing in rank (the standard Holm
    "running max" construction) — this is what makes Holm uniformly more
    powerful than plain Bonferroni while still controlling FWER exactly."""
    n = len(labeled_p_values)
    ordered = sorted(labeled_p_values, key=lambda lp: lp[1])

    adjusted: dict[str, float] = {}
    rejected_labels: set[str] = set()
    running_max = 0.0
    keep_rejecting = True
    for k, (label, p) in enumerate(ordered, start=1):
        step_adj = min(1.0, p * (n - k + 1))
        running_max = max(running_max, step_adj)  # monotonicity: adjusted p-values are non-decreasing in rank
        adjusted[label] = running_max
        if keep_rejecting and step_adj < alpha:
            rejected_labels.add(label)
        else:
            keep_rejecting = False  # once one comparison fails, every subsequent (larger-p) test is non-significant too

    results = [CorrectedResult(label=label, raw_p_value=p, adjusted_p_value=adjusted[label], significant_at_alpha=label in rejected_labels) for label, p in labeled_p_values]
    return MultipleTestingReport(
        method="Holm-Bonferroni (step-down, FWER control)", alpha=alpha, n_tests=n, results=tuple(results),
        n_significant=len(rejected_labels),
        guidance="Holm-Bonferroni controls FWER like Bonferroni but is uniformly more powerful (rejects at least as many). Prefer this over plain Bonferroni whenever FWER control is the goal.",
    )


def benjamini_hochberg_fdr(labeled_p_values: Sequence[tuple[str, float]], *, alpha: float = 0.05) -> MultipleTestingReport:
    """Step-up procedure controlling the False Discovery Rate: sort
    ascending, find the LARGEST k such that p_(k) <= (k/n)*alpha, reject
    all tests with rank <= that k. Less conservative than FWER methods —
    controls the expected PROPORTION of false discoveries among rejected
    hypotheses, not the probability of any false discovery at all."""
    n = len(labeled_p_values)
    ordered = sorted(labeled_p_values, key=lambda lp: lp[1])
    threshold_k = 0
    for k, (_label, p) in enumerate(ordered, start=1):
        if p <= (k / n) * alpha:
            threshold_k = k  # keep the LARGEST k satisfying the condition
    rejected_labels = {label for label, _p in ordered[:threshold_k]}

    # BH adjusted p-value: p_adj(k) = min_{j>=k} (n/j) * p_(j), enforced monotone non-increasing from the top.
    adjusted: dict[str, float] = {}
    running_min = 1.0
    for k in range(n, 0, -1):
        label, p = ordered[k - 1]
        candidate = min(1.0, (n / k) * p)
        running_min = min(running_min, candidate)
        adjusted[label] = running_min

    results = [CorrectedResult(label=label, raw_p_value=p, adjusted_p_value=adjusted[label], significant_at_alpha=label in rejected_labels) for label, p in labeled_p_values]
    return MultipleTestingReport(
        method="Benjamini-Hochberg (FDR control)", alpha=alpha, n_tests=n, results=tuple(results),
        n_significant=len(rejected_labels),
        guidance="Benjamini-Hochberg controls the expected FRACTION of false discoveries among rejected hypotheses, not FWER. Less conservative — appropriate for exploratory research over a large family where some false positives are tolerable.",
    )

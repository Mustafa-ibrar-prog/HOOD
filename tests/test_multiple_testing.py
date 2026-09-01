"""Phase 7, Part 2 & 19: multiple-testing correction tests."""

from __future__ import annotations

from src.research.multiple_testing import benjamini_hochberg_fdr, bonferroni_correction, holm_bonferroni_correction

CLASSIC_EXAMPLE = [("h1", 0.01), ("h2", 0.02), ("h3", 0.03), ("h4", 0.04), ("h5", 0.05)]


def test_bonferroni_classic_example():
    r = bonferroni_correction(CLASSIC_EXAMPLE, alpha=0.05)
    sig = {res.label for res in r.results if res.significant_at_alpha}
    assert sig == set()  # none clear 0.05/5 = 0.01 strictly


def test_holm_is_at_least_as_powerful_as_bonferroni():
    b = bonferroni_correction(CLASSIC_EXAMPLE, alpha=0.05)
    h = holm_bonferroni_correction(CLASSIC_EXAMPLE, alpha=0.05)
    b_sig = {r.label for r in b.results if r.significant_at_alpha}
    h_sig = {r.label for r in h.results if r.significant_at_alpha}
    assert b_sig.issubset(h_sig)


def test_bh_classic_example_rejects_all_five():
    r = benjamini_hochberg_fdr(CLASSIC_EXAMPLE, alpha=0.05)
    sig = {res.label for res in r.results if res.significant_at_alpha}
    assert sig == {"h1", "h2", "h3", "h4", "h5"}


def test_bh_is_at_least_as_powerful_as_holm():
    h = holm_bonferroni_correction(CLASSIC_EXAMPLE, alpha=0.05)
    fdr = benjamini_hochberg_fdr(CLASSIC_EXAMPLE, alpha=0.05)
    h_sig = {r.label for r in h.results if r.significant_at_alpha}
    fdr_sig = {r.label for r in fdr.results if r.significant_at_alpha}
    assert h_sig.issubset(fdr_sig)


def test_all_large_p_values_reject_nothing_under_any_method():
    large_ps = [("a", 0.5), ("b", 0.6), ("c", 0.7)]
    for method in (bonferroni_correction, holm_bonferroni_correction, benjamini_hochberg_fdr):
        r = method(large_ps, alpha=0.05)
        assert r.n_significant == 0


def test_single_very_small_p_value_significant_under_all_methods():
    ps = [("a", 0.0001), ("b", 0.8), ("c", 0.9)]
    for method in (bonferroni_correction, holm_bonferroni_correction, benjamini_hochberg_fdr):
        r = method(ps, alpha=0.05)
        assert any(res.label == "a" and res.significant_at_alpha for res in r.results)


def test_adjusted_p_values_are_never_less_than_raw():
    for method in (bonferroni_correction, holm_bonferroni_correction, benjamini_hochberg_fdr):
        r = method(CLASSIC_EXAMPLE, alpha=0.05)
        for res in r.results:
            assert res.adjusted_p_value >= res.raw_p_value - 1e-9


def test_reports_include_method_name_and_guidance_text():
    r = benjamini_hochberg_fdr(CLASSIC_EXAMPLE)
    assert "FDR" in r.method
    assert "false discoveries" in r.guidance.lower() or "fdr" in r.guidance.lower()
    rendered = r.render()
    assert "Benjamini-Hochberg" in rendered

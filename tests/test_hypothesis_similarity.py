"""Phase 7, Part 4 & 19: p-hacking defense via hypothesis similarity."""

from __future__ import annotations

from src.research.hypothesis_similarity import HypothesisFingerprint, bucket_threshold, check_research_reuse, similarity_score


def _fp(hid, family="momentum", feature="roc_20", horizon=5, universe="U1", bucket="[15..25)", cost="1x", exec_="next_bar"):
    return HypothesisFingerprint(hypothesis_id=hid, family=family, feature_variant=feature, target_horizon_bars=horizon, universe_name=universe, threshold_bucket=bucket, cost_assumptions=cost, execution_assumptions=exec_)


def test_bucket_threshold_groups_nearby_values_together():
    assert bucket_threshold(20, bucket_width=10) == bucket_threshold(22, bucket_width=10)
    assert bucket_threshold(20, bucket_width=10) != bucket_threshold(60, bucket_width=10)


def test_bucket_threshold_rejects_non_positive_width():
    import pytest
    with pytest.raises(ValueError):
        bucket_threshold(20, bucket_width=0)


def test_identical_fingerprints_score_1():
    a = _fp("A")
    b = _fp("B")
    assert similarity_score(a, b) == 1.0


def test_completely_different_fingerprints_score_0():
    a = _fp("A", family="momentum", feature="roc_20", horizon=5, universe="U1", bucket="b1", cost="1x", exec_="next_bar")
    b = _fp("B", family="mean_reversion", feature="zscore_5", horizon=20, universe="U2", bucket="b2", cost="2x", exec_="delayed")
    assert similarity_score(a, b) == 0.0


def test_same_family_and_feature_different_bucket_is_the_canonical_p_hacking_pattern():
    """This is the exact "5/10/15/20/25/30-day momentum" scenario the
    prompt names — same family, same feature TYPE, only the lookback
    bucket differs."""
    momentum_20 = _fp("MOM-20", bucket="[15..25)")
    momentum_60 = _fp("MOM-60", bucket="[55..65)")
    s = similarity_score(momentum_20, momentum_60)
    assert 0.5 < s < 1.0  # high but not perfect — family+feature match, bucket differs


def test_check_research_reuse_flags_a_similar_prior_hypothesis():
    prior = [_fp("MOM-20-old", bucket="[15..25)")]
    new = _fp("MOM-22-new", bucket="[15..25)")  # same bucket -> should flag as near-duplicate
    result = check_research_reuse(new, prior, similarity_threshold=0.70)
    assert result.flagged is True
    assert result.matches[0][0] == "MOM-20-old"
    assert "POTENTIAL_RESEARCH_REUSE" in result.explanation or "similarity" in result.explanation


def test_check_research_reuse_does_not_flag_a_distinct_hypothesis():
    prior = [_fp("MOM-20-old", family="momentum", feature="roc_20")]
    new = _fp("MR-5-new", family="mean_reversion", feature="zscore_5", horizon=5, bucket="[0..10)")
    result = check_research_reuse(new, prior, similarity_threshold=0.70)
    assert result.flagged is False
    assert result.matches == ()


def test_check_research_reuse_never_blocks_only_flags():
    """The function has no return value or side effect that could halt
    execution — it only reports."""
    prior = [_fp("A")]
    new = _fp("A")  # even a perfect self-match just gets reported, not raised
    result = check_research_reuse(new, prior)
    assert isinstance(result.flagged, bool)


def test_check_research_reuse_excludes_self_from_matches():
    prior = [_fp("SAME_ID")]
    new = _fp("SAME_ID")
    result = check_research_reuse(new, prior)
    assert result.matches == ()  # a hypothesis is never "similar to itself"


def test_canonical_hash_is_stable_and_ignores_hypothesis_id():
    a = _fp("A")
    b = _fp("B")  # different id, identical everything else
    assert a.canonical_hash() == b.canonical_hash()
    c = _fp("C", feature="zscore_5")
    assert a.canonical_hash() != c.canonical_hash()

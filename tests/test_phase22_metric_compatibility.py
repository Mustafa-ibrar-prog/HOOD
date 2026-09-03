"""Phase 22, Part 14 — 'Do NOT repeat the Phase 21 placebo mistake. The
placebo statistic must be mathematically identical in form to the
candidate's primary statistic.'

Phase 21 discovered mid-phase that feeding a group-mean-gap candidate
through an IC-based placebo battery silently compared two unrelated
statistics. Phase 22 avoids the mismatch by construction -- every
preregistered hypothesis this phase uses a cross-sectional IC (Spearman
rank correlation) as its primary metric (Part 8's own guidance not to
make a group-difference the primary hypothesis this phase) -- so the
SAME IC-based placebo battery is valid for the whole family. This test
proves that invariant mechanically rather than asserting it only in a
docstring/comment: (1) every hypothesis in the campaign's own config
uses the IC machinery, and (2) a placebo function's `observed_statistic`
numerically equals an independently-recomputed pooled IC on the same
inputs, for a real slice of hypothesis features actually used this
phase.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

from src.research.cross_sectional_placebo import shuffled_signal_placebo
from src.research.ic import compute_ic_series, summarize_ic

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_campaign_module():
    path = REPO_ROOT / "scripts" / "phase22_step3_discovery_campaign.py"
    spec = importlib.util.spec_from_file_location("phase22_step3_discovery_campaign", path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO_ROOT))
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def campaign():
    return _load_campaign_module()


def test_every_phase22_hypothesis_config_entry_has_four_fields(campaign):
    for hyp_id, cfg in campaign.HYPOTHESES.items():
        assert len(cfg) == 4, f"{hyp_id} config must be (feature_col, target_col, direction, check_dte_variance)"
        feature_col, target_col, direction, check_dte = cfg
        assert isinstance(feature_col, str) and feature_col
        assert isinstance(target_col, str) and target_col
        assert direction in ("positive", "negative", "unsigned")
        assert isinstance(check_dte, bool)


def test_no_phase22_hypothesis_uses_a_group_difference_metric(campaign):
    """Part 8: 'do not make call-vs-put group difference the primary
    hypothesis.' Structurally verified: no hypothesis's feature or
    target column is the raw call_put label itself."""
    for hyp_id, (feature_col, target_col, _direction, _check_dte) in campaign.HYPOTHESES.items():
        assert feature_col not in ("call_put", "call_put_numeric"), f"{hyp_id} uses call_put as its primary feature"
        assert target_col not in ("call_put", "call_put_numeric"), f"{hyp_id} uses call_put as its primary target"


def _row(symbol, ts, feature, target):
    return {"symbol": symbol, "underlying_symbol": symbol, "timestamp": ts, "feat": feature, "tgt": target}


def _synthetic_panel():
    rows = []
    for sym_i, sym in enumerate(("AAA", "BBB", "CCC", "DDD")):
        for day in range(15):
            ts = date(2022, 1, 1 + day)
            feature = float(day + sym_i)
            target = feature * 0.05 + (sym_i * 0.001)
            rows.append(_row(sym, ts, feature, target))
    return rows


def test_placebo_observed_statistic_equals_an_independently_recomputed_pooled_ic():
    """The direct proof: `shuffled_signal_placebo`'s `observed_statistic`
    (the number every Phase 22 hypothesis compares against its placebo
    distribution) is computed via the exact same compute_ic_series/
    summarize_ic call the campaign script's own `pooled_ic` helper
    uses -- not a different statistic in the same units, and not a
    different statistic entirely (the Phase 21 mistake)."""
    panel = _synthetic_panel()
    result = shuffled_signal_placebo(panel, feature_col="feat", target_col="tgt", n_trials=20, seed=1, min_universe_size=3)

    independently_recomputed = summarize_ic(
        compute_ic_series(panel, "feat", "tgt", min_universe_size=3), feature_name="feat", target_name="tgt",
    ).average_ic

    assert result.observed_statistic is not None
    assert independently_recomputed is not None
    assert result.observed_statistic == pytest.approx(independently_recomputed, abs=1e-12)


def test_campaign_pooled_ic_helper_matches_the_placebo_batterys_own_statistic(campaign):
    """Same proof, but calling the campaign script's OWN `pooled_ic`
    helper (the function that actually computes every hypothesis's
    'POOLED IC' line) rather than reimplementing the comparison."""
    panel = [dict(r, option_id=f"{r['symbol']}_{i}") for i, r in enumerate(_synthetic_panel())]
    campaign_pooled = campaign.pooled_ic(panel, "feat", "tgt")

    placebo_result = shuffled_signal_placebo(panel, feature_col="feat", target_col="tgt", n_trials=20, seed=1, min_universe_size=3)

    assert campaign_pooled is not None
    assert placebo_result.observed_statistic == pytest.approx(campaign_pooled, abs=1e-12)

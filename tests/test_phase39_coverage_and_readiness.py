"""Phase 39, Part 10-12 — coverage reporting and objective
validation-readiness milestones (never a claim of validity)."""

from __future__ import annotations

import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.options.phase38_causal_validation_dataset import CausalFeatureRow
from src.options.phase38_underlying_vs_option_edge import MIN_SAMPLE_FOR_A_VERDICT
from src.options.phase39_readiness import ReadinessStatus, assess_collection_readiness
from src.research_recorder.coverage_report import CoverageReport, build_coverage_report
from src.research_recorder.normalized_observation import build_normalized_option_observation, build_normalized_underlying_observation
from src.research_recorder.recorder import RecorderStores
from src.research_recorder.storage import CycleLogStore, NormalizedOptionStore, NormalizedUnderlyingStore, RawObservationStore, ResearchSignalStore

NOW = datetime(2026, 9, 8, 15, 0, tzinfo=timezone.utc)


def _stores(tmp_path):
    return RecorderStores(
        raw=RawObservationStore(tmp_path / "raw.jsonl"), underlying=NormalizedUnderlyingStore(tmp_path / "underlying.jsonl"),
        option=NormalizedOptionStore(tmp_path / "option.jsonl"), signal=ResearchSignalStore(tmp_path / "signal.jsonl"),
        cycle_log=CycleLogStore(tmp_path / "cycle_log.jsonl"),
    )


def _row(*, option_id="opt-1", underlying="AAPL", cycle="cyc-0", t=NOW, iv=0.3, greeks=True, volume=100, oi=200, dte=None, moneyness=None):
    return CausalFeatureRow(
        observation_cycle_id=cycle, observation_timestamp=t, underlying_symbol=underlying, option_id=option_id,
        option_type="call", strike=230.0, expiration=(t.date() + timedelta(days=30)), dte=dte if dte is not None else 30,
        moneyness=moneyness if moneyness is not None else 0.0,
        underlying_last=230.0, underlying_bid=229.0, underlying_ask=231.0, underlying_midpoint=230.0,
        option_bid=1.0, option_ask=1.05, option_bid_size=5, option_ask_size=7, option_mark=1.02, option_midpoint=1.025,
        implied_volatility=iv, delta=0.5 if greeks else None, gamma=0.1 if greeks else None, theta=-0.02 if greeks else None,
        vega=0.05 if greeks else None, rho=0.01 if greeks else None, open_interest=oi, volume=volume,
        contract_state="active", contract_tradability="tradable", field_provenance={}, raw_payload_fingerprint="fp",
    )


# --- Coverage report -----------------------------------------------------------------------------


def test_coverage_report_on_empty_stores_has_no_availability_percentages():
    with tempfile.TemporaryDirectory() as d:
        report = build_coverage_report(_stores(Path(d)))
        assert report.total_cycles == 0
        assert report.implied_volatility_availability_pct is None
        assert report.observations_per_contract_mean is None


def test_coverage_report_composes_data_quality_report_not_duplicates_it():
    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        stores.underlying.append(build_normalized_underlying_observation(
            symbol="AAPL", observation_cycle_id="cyc-0", observation_timestamp=NOW, quote_row={"last_trade_price": "230.0"},
        ))
        stores.option.append(build_normalized_option_observation(
            option_id="opt-1", underlying="AAPL", observation_cycle_id="cyc-0", observation_timestamp=NOW,
            market_timezone="America/New_York", quote_row={"bid_price": "1.0", "ask_price": "1.05", "implied_volatility": "0.3",
                "delta": "0.5", "gamma": "0.1", "theta": "-0.02", "vega": "0.05", "rho": "0.01", "volume": "100", "open_interest": "200"},
            chain_row={"type": "call", "strike_price": "230.0", "expiration_date": (NOW.date() + timedelta(days=30)).isoformat(),
                       "state": "active", "tradability": "tradable"},
            underlying_price=230.0,
        ))
        report = build_coverage_report(stores)
        assert report.data_quality.option_contracts_observed == 1
        assert report.contracts_observed_by_symbol == {"AAPL": 1}
        assert report.implied_volatility_availability_pct == 1.0
        assert report.greeks_availability_pct == 1.0
        assert report.volume_availability_pct == 1.0
        assert report.open_interest_availability_pct == 1.0
        assert report.observations_per_contract_mean == 1.0
        assert report.observations_per_contract_max == 1


def test_coverage_report_tracks_repeated_observations_of_the_same_contract():
    with tempfile.TemporaryDirectory() as d:
        stores = _stores(Path(d))
        for i in range(3):
            t = NOW + timedelta(minutes=5 * i)
            stores.option.append(build_normalized_option_observation(
                option_id="opt-1", underlying="AAPL", observation_cycle_id=f"cyc-{i}", observation_timestamp=t,
                market_timezone="America/New_York", quote_row={"bid_price": "1.0", "ask_price": "1.05"},
                chain_row={"type": "call", "strike_price": "230.0", "expiration_date": (NOW.date() + timedelta(days=30)).isoformat(),
                           "state": "active", "tradability": "tradable"},
                underlying_price=230.0,
            ))
        report = build_coverage_report(stores)
        assert report.observations_per_contract_max == 3
        assert report.observations_per_contract_mean == 3.0


def test_coverage_report_never_computes_an_alpha_signal_field():
    """Same discipline as Phase 37's own DataQualityReport -- no field
    named anything like score/edge/expectancy/signal."""
    from dataclasses import fields

    forbidden_substrings = ("score", "edge", "expectancy", "signal", "profit", "return")
    for f in fields(CoverageReport):
        name = f.name.lower()
        assert not any(s in name for s in forbidden_substrings), f"CoverageReport.{f.name} looks like an alpha/trading field"


# --- Readiness assessment -------------------------------------------------------------------------


def test_readiness_is_insufficient_with_zero_rows():
    result = assess_collection_readiness([])
    assert result.status == ReadinessStatus.INSUFFICIENT_DATA_FOR_VALIDATION
    assert len(result.unmet_gating_milestone_keys) > 0


def test_readiness_never_declares_sufficiency_with_only_one_contract():
    rows = [_row(t=NOW + timedelta(minutes=5 * i)) for i in range(5)]  # one contract, repeated -- not "multiple contracts"
    result = assess_collection_readiness(rows)
    assert result.status == ReadinessStatus.INSUFFICIENT_DATA_FOR_VALIDATION
    assert "C_multiple_independent_contracts" in result.unmet_gating_milestone_keys
    assert "D_multiple_underlying_symbols" in result.unmet_gating_milestone_keys


def test_readiness_thresholds_reuse_phase38_constants_verbatim():
    """Never an arbitrarily-chosen sample size -- literally imports
    Phase 38's own constant and checks the milestone detail names it."""
    result = assess_collection_readiness([])
    c_milestone = next(m for m in result.milestones if m.key == "C_multiple_independent_contracts")
    assert str(MIN_SAMPLE_FOR_A_VERDICT) in c_milestone.detail


def test_readiness_market_regime_milestone_is_informational_only_never_gates():
    result = assess_collection_readiness([])
    f_milestone = next(m for m in result.milestones if m.key == "F_multiple_market_regimes")
    assert f_milestone.gating is False
    assert f_milestone.satisfied is True
    assert "F_multiple_market_regimes" not in result.unmet_gating_milestone_keys


def test_readiness_reaches_sufficient_for_validation_attempt_with_enough_synthetic_rows():
    """Proves the plumbing/thresholds are wired correctly end to end with
    a large synthetic multi-symbol, multi-day, multi-contract dataset --
    never presented as real evidence for any real strategy (same
    discipline as Phase 38's _full_passing_evidence fixture)."""
    rows = []
    symbols = ["AAPL", "MSFT"]
    for day in range(3):
        for sym in symbols:
            for c in range(15):  # 2 symbols * 3 days * 15 contracts = 90 unique option_ids
                base_t = NOW + timedelta(days=day)
                for k in range(2):  # repeated observations per contract
                    rows.append(_row(option_id=f"opt-{sym}-{day}-{c}", underlying=sym, cycle=f"cyc-{day}-{c}-{k}", t=base_t + timedelta(minutes=5 * k)))
    result = assess_collection_readiness(rows)
    assert result.status == ReadinessStatus.SUFFICIENT_FOR_VALIDATION_ATTEMPT
    assert result.unmet_gating_milestone_keys == ()


def test_readiness_status_is_never_a_claim_about_strategy_validity():
    """The enum value itself must never contain the word VALIDATED or
    READY as a standalone claim about a strategy -- only about data."""
    for status in ReadinessStatus:
        assert "VALIDATED_STRATEGY" not in status.value
        assert status.value in ("INSUFFICIENT_DATA_FOR_VALIDATION", "SUFFICIENT_FOR_VALIDATION_ATTEMPT")

#!/usr/bin/env python3
"""Phase 18 — STEP 0: the options data capability audit and final
decision gate.

Prints the real, evidence-backed OPTIONS_CAPABILITY_MATRIX
(src/options/capability_audit.py) and demonstrates the new architecture
working end-to-end on the REAL contract/price data this phase's
development probed (a real AAPL Jan-2022-expiry $175 call, and a real
deep-OTM $25 put from the same expiration, both fetched via genuine
read-only mcp__HOOD__get_option_instruments / get_option_historicals /
get_option_quotes calls). Nothing here calls a HOOD MCP tool itself (this
process cannot) -- the values below are transcribed from those real
calls, exactly like every prior phase's ingestion scripts.

No alpha computation, no strategy, no order placement anywhere in this
script (Part 19/20).
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.execution.asset_class_restriction import ASSET_CLASS_RESTRICTION, NonOptionsOrderRejected, assert_options_only  # noqa: E402
from src.execution.orders import OrderLeg, OrderRequest  # noqa: E402
from src.options import (  # noqa: E402
    OPTIONS_CAPABILITY_MATRIX,
    ContractExistenceEvidence,
    Greeks,
    GreeksProvenance,
    IVObservation,
    IVProvenance,
    OptionChainObservation,
    OptionContract,
    OptionLegPosition,
    OptionsPosition,
    OptionsSourceCapability,
    analyze_position_risk,
    compute_liquidity_metrics,
    contract_existed_at,
    validate_greeks,
    validate_iv,
    validate_observation,
)


def _print_header(title: str) -> None:
    print("\n" + "=" * 100, flush=True)
    print(title, flush=True)
    print("=" * 100, flush=True)


def part_capability_matrix() -> None:
    _print_header("PART 6-8 — OPTIONS DATA CAPABILITY MATRIX (real probes)")
    for row in OPTIONS_CAPABILITY_MATRIX:
        print(f"\n  --- {row.data_field} ---", flush=True)
        print(f"      capability={row.capability.value}", flush=True)
        print(f"      historical_depth={row.historical_depth}", flush=True)
        print(f"      evidence={row.evidence}", flush=True)
        print(f"      MAJOR CAVEAT: {row.major_caveat}", flush=True)


def part_real_contract_demo() -> tuple[OptionContract, OptionContract]:
    _print_header("PART 2-3 — REAL CONTRACT + CHAIN OBSERVATION DEMONSTRATION")
    # Real, transcribed from a genuine get_option_instruments(chain_symbol="AAPL", state="expired",
    # expiration_dates="2022-01-21", strike_price="175.0000", type="call") probe.
    near_the_money = OptionContract(
        underlying_symbol="AAPL", option_id="c55a630e-a0b9-45ab-b889-47bee291fee7", call_put="call",
        strike=175.0, expiration=date(2022, 1, 21), retrieval_timestamp=datetime(2026, 9, 3, tzinfo=timezone.utc),
    )
    # Real, transcribed from get_option_instruments(..., strike_price="25.0000", type="put").
    deep_otm = OptionContract(
        underlying_symbol="AAPL", option_id="55f58340-b07f-4591-b1bd-1292a8af3d96", call_put="put",
        strike=25.0, expiration=date(2022, 1, 21), retrieval_timestamp=datetime(2026, 9, 3, tzinfo=timezone.utc),
    )
    print(f"  near-the-money: {near_the_money.occ_style_description}  id={near_the_money.option_id}", flush=True)
    print(f"  deep-OTM:       {deep_otm.occ_style_description}  id={deep_otm.option_id}", flush=True)

    # Real historical closes, transcribed from the actual get_option_historicals response.
    ntm_closes = [
        (date(2021, 12, 1), 3.53), (date(2021, 12, 10), 9.63), (date(2022, 1, 3), 8.45),
        (date(2022, 1, 14), 1.38), (date(2022, 1, 19), 0.07), (date(2022, 1, 20), 0.01),
    ]
    print("\n  Real near-the-money OHLC closes (rich, volatile, genuine price decay toward expiration):", flush=True)
    observations = []
    for d, close in ntm_closes:
        obs = OptionChainObservation.from_historical_bar(near_the_money, observation_timestamp=datetime(d.year, d.month, d.day, tzinfo=timezone.utc), close_price=close)
        observations.append(obs)
        issues = validate_observation(obs)
        print(f"    {d}: close={close}  quality_issues={issues}", flush=True)

    otm_closes = [(date(2021, 12, 1), 0.01), (date(2022, 1, 10), 0.01), (date(2022, 1, 20), 0.01)]
    print("\n  Real deep-OTM OHLC closes (flat every day -- plausible tick-floor pinning, NOT independently", flush=True)
    print("  confirmed genuine; documented as a caveat per OPTIONS_CAPABILITY_MATRIX):", flush=True)
    for d, close in otm_closes:
        print(f"    {d}: close={close}", flush=True)

    return near_the_money, deep_otm


def part_greeks_iv_demo() -> None:
    _print_header("PART 12-13 — GREEKS / IV DEMONSTRATION (real LIVE probe, AAPL $230C 2026-09-18)")
    # Real, transcribed from a genuine get_option_quotes probe against a live, active contract.
    greeks = Greeks.observed(delta=0.982989, gamma=0.000756, theta=-0.097964, vega=0.028455, rho=0.096388)
    iv = IVObservation.observed(0.822619)
    print(f"  Greeks: {greeks}", flush=True)
    print(f"  Greeks quality issues: {validate_greeks(greeks)}", flush=True)
    print(f"  IV: {iv}", flush=True)
    print(f"  IV quality issues: {validate_iv(iv)}", flush=True)
    print("\n  CONFIRMED: this live payload also included bid=94.30, ask=97.15, bid_size=85, ask_size=54,", flush=True)
    print("  open_interest=1709, volume=2 -- none of Greeks/IV/bid_size/ask_size are currently parsed into", flush=True)
    print("  src.market.models.OptionQuote (a real, documented, unclaimed extension point).", flush=True)


def part_pit_demo(near_the_money: OptionContract) -> None:
    _print_header("PART 5 — POINT-IN-TIME CONTRACT EXISTENCE DEMONSTRATION")
    evidence = ContractExistenceEvidence(contract=near_the_money, first_listed_date=None, expiration=near_the_money.expiration, source="mcp__HOOD__get_option_instruments")
    before = contract_existed_at(evidence, as_of=datetime(2021, 6, 1, tzinfo=timezone.utc))
    after_expiration = contract_existed_at(evidence, as_of=datetime(2022, 6, 1, tzinfo=timezone.utc))
    print(f"  contract_existed_at(2021-06-01) [well before expiration, listing date unknown]: {before}  (honest 'unknown', never guessed True)", flush=True)
    print(f"  contract_existed_at(2022-06-01) [after expiration]: {after_expiration}  (correctly False)", flush=True)


def part_position_demo(near_the_money: OptionContract) -> None:
    _print_header("PART 11 — OPTIONS POSITION / RISK PROFILE DEMONSTRATION")
    leg = OptionLegPosition(contract=near_the_money, side="long", quantity=1, entry_price=3.53, entry_timestamp=datetime(2021, 12, 1, tzinfo=timezone.utc))
    position = OptionsPosition(legs=(leg,), opened_at=datetime(2021, 12, 1, tzinfo=timezone.utc), strategy_label="long_call")
    risk = analyze_position_risk(position)
    print(f"  single-leg long call: {risk}", flush=True)

    # A vertical: long the 175C, short a hypothetical 180C, same expiration.
    short_contract = OptionContract(underlying_symbol="AAPL", option_id="hypothetical-180c", call_put="call", strike=180.0, expiration=near_the_money.expiration)
    short_leg = OptionLegPosition(contract=short_contract, side="short", quantity=1, entry_price=1.80, entry_timestamp=datetime(2021, 12, 1, tzinfo=timezone.utc))
    spread = OptionsPosition(legs=(leg, short_leg), opened_at=datetime(2021, 12, 1, tzinfo=timezone.utc), strategy_label="bull_call_spread")
    spread_risk = analyze_position_risk(spread)
    print(f"  2-leg bull call spread (175/180): {spread_risk}", flush=True)

    # An unsupported 3-leg structure -- must return UNSUPPORTED, never a guessed number.
    third_leg = OptionLegPosition(contract=OptionContract(underlying_symbol="AAPL", option_id="hypothetical-185c", call_put="call", strike=185.0, expiration=near_the_money.expiration), side="long", quantity=1, entry_price=0.90, entry_timestamp=datetime(2021, 12, 1, tzinfo=timezone.utc))
    butterfly = OptionsPosition(legs=(leg, short_leg, short_leg, third_leg), opened_at=datetime(2021, 12, 1, tzinfo=timezone.utc))
    butterfly_risk = analyze_position_risk(butterfly)
    print(f"  4-leg structure (unsupported by this implementation): {butterfly_risk.method}", flush=True)


def part_options_only_execution_demo() -> None:
    _print_header("PART 10 — OPTIONS-ONLY EXECUTION RESTRICTION DEMONSTRATION")
    print(f"  ASSET_CLASS_RESTRICTION = {ASSET_CLASS_RESTRICTION!r}", flush=True)
    valid = OrderRequest(account_number="acct1", legs=(OrderLeg(option_id="c55a630e-a0b9-45ab-b889-47bee291fee7", side="buy", position_effect="open"),), quantity="1", price="3.53")
    assert_options_only(valid)
    print("  a real options OrderRequest passes assert_options_only()", flush=True)
    try:
        bad = OrderRequest(account_number="acct1", legs=(OrderLeg(option_id="", side="buy", position_effect="open"),), quantity="100", price="230.00")
        assert_options_only(bad)
        print("  UNEXPECTED: should have raised", flush=True)
    except NonOptionsOrderRejected as exc:
        print(f"  a malformed/non-options-shaped order is correctly REJECTED: {exc}", flush=True)
    print("\n  Repository-wide audit: OrderLeg REQUIRES option_id (no shares/equity_symbol field exists anywhere", flush=True)
    print("  on OrderRequest/OrderLeg); place_equity_order/review_equity_order/cancel_equity_order are named", flush=True)
    print("  exactly once in the entire src/ tree (a docstring in src/market/hood_client.py documenting their", flush=True)
    print("  deliberate absence) and never actually called anywhere. This system is options-only by", flush=True)
    print("  construction, confirmed via static repository inspection (see tests/test_phase18_safety.py).", flush=True)


def part_final_decision_gate() -> None:
    _print_header("PART 24 — FINAL DECISION GATE")
    summary = {}
    for row in OPTIONS_CAPABILITY_MATRIX:
        summary.setdefault(row.capability, []).append(row.data_field)
    for cap, fields in summary.items():
        print(f"  {cap.value}: {fields}", flush=True)

    print("\nCLASSIFICATION: OPTIONS_RESEARCH_READY_WITH_LIMITATIONS", flush=True)
    print("", flush=True)
    print("Rationale: contract identity (strike/type/expiration) and historical OHLC price bars for", flush=True)
    print("individual contracts ARE real and confirmed available across the 2021-2023 discovery window --", flush=True)
    print("this supports directional, mark-at-close options research (e.g. long calls/puts held to a", flush=True)
    print("target/stop/expiration, priced off historical closes). It does NOT support execution-realism-", flush=True)
    print("or liquidity-sensitive research: historical bid/ask, volume, open interest, IV, and Greeks are", flush=True)
    print("all confirmed UNAVAILABLE for any past date -- any future backtest must ASSUME a spread/slippage", flush=True)
    print("model rather than observe one, and must not claim liquidity-based position sizing was validated", flush=True)
    print("against real historical liquidity data. This is NOT HISTORICAL_OPTIONS_DATA_INSUFFICIENT: real,", flush=True)
    print("usable historical option PRICE data exists and was independently verified, not merely assumed.", flush=True)


def main() -> None:
    part_capability_matrix()
    near_the_money, _deep_otm = part_real_contract_demo()
    part_greeks_iv_demo()
    part_pit_demo(near_the_money)
    part_position_demo(near_the_money)
    part_options_only_execution_demo()
    part_final_decision_gate()
    _print_header("DONE — options data/instrument architecture only. No options alpha hypothesis tested, no trading strategy created.")


if __name__ == "__main__":
    main()

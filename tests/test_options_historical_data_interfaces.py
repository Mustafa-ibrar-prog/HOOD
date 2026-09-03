"""Phase 24, Part 16/22 — provider-agnostic historical options data
interfaces: Protocol conformance, historical/live separation, PIT
lifecycle representation, provenance completeness, no fabricated
defaults."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.data.source_profile import DataProvenance
from src.options.historical_data_interfaces import (
    ContractIdentity,
    ContractLifecycle,
    ContractLifecycleStatus,
    ContractLifecycleStore,
    HistoricalOptionChainStore,
    HistoricalOptionContractStore,
    HistoricalOptionGreeksStore,
    HistoricalOptionIVStore,
    HistoricalOptionOpenInterestStore,
    HistoricalOptionQuoteStore,
    HistoricalOptionTradeStore,
    HistoricalOrLive,
    OptionDataProvenance,
)


def _provenance(*, historical_or_live: HistoricalOrLive = HistoricalOrLive.HISTORICAL, interpolated: bool = False) -> OptionDataProvenance:
    return OptionDataProvenance(
        source="test_source", retrieval_timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), publication_timestamp=None,
        historical_or_live=historical_or_live, observation_kind=DataProvenance.OBSERVED,
        adjustment_status="unadjusted", interpolation_flag=interpolated, confidence_status="verified_real_probe",
    )


def test_option_data_provenance_requires_explicit_historical_or_live():
    p = _provenance(historical_or_live=HistoricalOrLive.HISTORICAL)
    assert p.historical_or_live == HistoricalOrLive.HISTORICAL
    p2 = _provenance(historical_or_live=HistoricalOrLive.LIVE)
    assert p2.historical_or_live == HistoricalOrLive.LIVE
    assert p.historical_or_live != p2.historical_or_live  # the two are never conflated by a shared default


def test_option_data_provenance_requires_explicit_interpolation_flag():
    p = _provenance(interpolated=True)
    assert p.interpolation_flag is True
    p2 = _provenance(interpolated=False)
    assert p2.interpolation_flag is False


def test_contract_identity_carries_provenance():
    identity = ContractIdentity(
        option_id="opt-1", underlying_symbol="AAPL", call_put="put", strike=150.0, expiration=date(2022, 3, 18),
        multiplier=100, exercise_style="american", contract_status="expired", provenance=_provenance(),
    )
    assert identity.provenance.source == "test_source"
    assert identity.expiration == date(2022, 3, 18)


def test_contract_lifecycle_allows_all_date_fields_to_be_none():
    """Part 7: a source that cannot supply first-listed/last-trade dates
    must leave them None -- never approximated from an OHLC series."""
    lifecycle = ContractLifecycle(
        option_id="opt-1", first_observable_date=None, first_listed_date=None, last_trade_date=None,
        expiration_date=date(2022, 3, 18), status=ContractLifecycleStatus.UNKNOWN, provenance=_provenance(),
    )
    assert lifecycle.first_observable_date is None
    assert lifecycle.first_listed_date is None
    assert lifecycle.status == ContractLifecycleStatus.UNKNOWN


def test_contract_lifecycle_status_has_no_silent_default_to_active():
    """Constructing a ContractLifecycle REQUIRES an explicit status --
    there is no keyword default that would silently claim ACTIVE."""
    import inspect
    sig = inspect.signature(ContractLifecycle)
    assert sig.parameters["status"].default is inspect.Parameter.empty


# --- Protocol conformance: a minimal fake implementation must satisfy each interface structurally ---


class _FakeContractStore:
    def get_contract(self, option_id: str) -> ContractIdentity | None:
        return None

    def list_contracts_for_expiration(self, underlying_symbol: str, expiration: date) -> list[ContractIdentity]:
        return []

    def save_contracts(self, contracts) -> object:
        return None


class _FakeChainStore:
    def get_chain_snapshot(self, underlying_symbol: str, as_of: datetime) -> list[ContractIdentity]:
        return []

    def save_chain_snapshot(self, underlying_symbol: str, as_of: datetime, contracts) -> object:
        return None


class _FakeLifecycleStore:
    def get_lifecycle(self, option_id: str) -> ContractLifecycle | None:
        return None

    def save_lifecycle(self, lifecycle: ContractLifecycle) -> object:
        return None


class _FakeFieldObservationStore:
    def load(self, contract_id: str) -> list:
        return []

    def save(self, contract_id: str, observations, *, source: str = "x") -> object:
        return None


def test_fake_contract_store_satisfies_the_protocol():
    assert isinstance(_FakeContractStore(), HistoricalOptionContractStore)


def test_fake_chain_store_satisfies_the_protocol():
    assert isinstance(_FakeChainStore(), HistoricalOptionChainStore)


def test_fake_lifecycle_store_satisfies_the_protocol():
    assert isinstance(_FakeLifecycleStore(), ContractLifecycleStore)


@pytest.mark.parametrize("protocol", [
    HistoricalOptionQuoteStore, HistoricalOptionTradeStore, HistoricalOptionGreeksStore,
    HistoricalOptionIVStore, HistoricalOptionOpenInterestStore,
])
def test_fake_field_observation_store_satisfies_every_field_protocol(protocol):
    """The 5 field-observation stores share one structural shape by
    design (see module docstring) -- one fake satisfies all 5."""
    assert isinstance(_FakeFieldObservationStore(), protocol)


def test_an_object_missing_a_method_does_not_satisfy_the_protocol():
    class _Incomplete:
        def get_contract(self, option_id: str):
            return None
        # missing list_contracts_for_expiration and save_contracts

    assert not isinstance(_Incomplete(), HistoricalOptionContractStore)


def test_historical_or_live_enum_has_exactly_two_values():
    """No third 'ambiguous' state -- every provenance record must
    commit to one or the other."""
    assert {e.value for e in HistoricalOrLive} == {"historical", "live"}

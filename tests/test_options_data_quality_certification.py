"""Phase 25, Part 23 — the future data quality certification
specification: exactly 15 criteria defined, none assessed against any
real provider yet (design only)."""

from __future__ import annotations

from src.options.data_quality_certification import (
    DATA_QUALITY_CERTIFICATION_SPEC,
    CertificationStatus,
    criterion_ids,
)


def test_spec_has_exactly_fifteen_criteria():
    assert len(DATA_QUALITY_CERTIFICATION_SPEC) == 15


def test_criterion_ids_are_unique_and_sequential():
    ids = criterion_ids()
    assert len(ids) == len(set(ids))
    assert ids == tuple(f"DQC-{i:02d}" for i in range(1, 16))


def test_every_criterion_has_a_real_title_and_description():
    for c in DATA_QUALITY_CERTIFICATION_SPEC:
        assert len(c.title) > 5
        assert len(c.description) > 20


def test_certification_status_has_only_not_yet_assessed():
    """This phase designs the spec -- it does not score anything against
    it (Part 23's explicit instruction)."""
    assert list(CertificationStatus) == [CertificationStatus.NOT_YET_ASSESSED]


def test_no_certification_result_type_exists_in_this_module():
    """A future phase, not this one, is allowed to introduce a scored
    result type."""
    import src.options.data_quality_certification as mod
    assert not hasattr(mod, "CertificationResult")

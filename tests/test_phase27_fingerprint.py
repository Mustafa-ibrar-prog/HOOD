"""Phase 27, Part 11/16 — the combined multi-directory fingerprint:
deterministic, order-independent, and sensitive to any real byte
change in any of the combined directories."""

from __future__ import annotations

from src.options.phase27_fingerprint import compute_combined_fingerprint


def test_combined_fingerprint_is_deterministic(tmp_path):
    d1, d2 = tmp_path / "d1", tmp_path / "d2"
    d1.mkdir()
    d2.mkdir()
    (d1 / "a.zip").write_bytes(b"content-a")
    (d2 / "b.zip").write_bytes(b"content-b")
    fp1 = compute_combined_fingerprint([d1, d2])
    fp2 = compute_combined_fingerprint([d1, d2])
    assert fp1 == fp2
    assert len(fp1) == 64


def test_combined_fingerprint_is_order_independent(tmp_path):
    d1, d2 = tmp_path / "d1", tmp_path / "d2"
    d1.mkdir()
    d2.mkdir()
    (d1 / "a.zip").write_bytes(b"content-a")
    (d2 / "b.zip").write_bytes(b"content-b")
    assert compute_combined_fingerprint([d1, d2]) == compute_combined_fingerprint([d2, d1])


def test_combined_fingerprint_changes_when_any_directory_changes(tmp_path):
    d1, d2 = tmp_path / "d1", tmp_path / "d2"
    d1.mkdir()
    d2.mkdir()
    (d1 / "a.zip").write_bytes(b"content-a")
    (d2 / "b.zip").write_bytes(b"content-b")
    fp_before = compute_combined_fingerprint([d1, d2])
    (d2 / "b.zip").write_bytes(b"content-b-modified")
    fp_after = compute_combined_fingerprint([d1, d2])
    assert fp_before != fp_after

"""Tests for scripts/run_btc_model_pipeline.py -- the single-command
orchestrator chaining download_btc_historical_bars.py and
backtest_btc_direction_model.py together. subprocess.run is replaced
with a deterministic fake throughout -- this file never actually spawns
a real Python process or makes a network call; it only verifies the
orchestration (what gets run, in what order, with what arguments, and
how a failure at each step is handled)."""

from __future__ import annotations

import sys
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.run_btc_model_pipeline as pipeline  # noqa: E402

_FakeCompletedProcess = namedtuple("_FakeCompletedProcess", ["returncode"])


def _patch_subprocess(monkeypatch, *, returncodes: list[int] | None = None):
    calls: list[list[str]] = []
    codes = iter(returncodes or [])

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        try:
            rc = next(codes)
        except StopIteration:
            rc = 0
        return _FakeCompletedProcess(returncode=rc)

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
    return calls


def _run(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["run_btc_model_pipeline.py", *argv])
    return pipeline.main()


def test_default_flow_runs_download_then_backtest_in_order(monkeypatch, tmp_path):
    calls = _patch_subprocess(monkeypatch, returncodes=[0, 0])
    bars_file = tmp_path / "bars.json"

    rc = _run(monkeypatch, ["--start", "2026-07-01", "--end", "2026-10-01", "--bars-file", str(bars_file)])

    assert rc == 0
    assert len(calls) == 2
    download_argv, backtest_argv = calls
    assert "download_btc_historical_bars.py" in download_argv[1]
    assert "--start" in download_argv and "2026-07-01" in download_argv
    assert "--end" in download_argv and "2026-10-01" in download_argv
    assert "--output" in download_argv and str(bars_file) in download_argv
    assert "backtest_btc_direction_model.py" in backtest_argv[1]
    assert "--bars-file" in backtest_argv and str(bars_file) in backtest_argv


def test_download_failure_stops_the_pipeline_before_backtest(monkeypatch, tmp_path):
    calls = _patch_subprocess(monkeypatch, returncodes=[1])
    rc = _run(monkeypatch, ["--start", "2026-07-01", "--bars-file", str(tmp_path / "bars.json")])

    assert rc == 1
    assert len(calls) == 1  # backtest step never ran


def test_backtest_failure_is_propagated(monkeypatch, tmp_path):
    calls = _patch_subprocess(monkeypatch, returncodes=[0, 3])
    rc = _run(monkeypatch, ["--start", "2026-07-01", "--bars-file", str(tmp_path / "bars.json")])

    assert rc == 3
    assert len(calls) == 2


def test_skip_download_with_existing_bars_file_only_runs_backtest(monkeypatch, tmp_path):
    bars_file = tmp_path / "bars.json"
    bars_file.write_text("[]")
    calls = _patch_subprocess(monkeypatch, returncodes=[0])

    rc = _run(monkeypatch, ["--skip-download", "--bars-file", str(bars_file)])

    assert rc == 0
    assert len(calls) == 1
    assert "backtest_btc_direction_model.py" in calls[0][1]


def test_skip_download_without_an_existing_bars_file_errors_before_any_subprocess(monkeypatch, tmp_path, capsys):
    calls = _patch_subprocess(monkeypatch)
    rc = _run(monkeypatch, ["--skip-download", "--bars-file", str(tmp_path / "missing.json")])

    assert rc == 2
    assert calls == []
    assert "does not exist" in capsys.readouterr().err


def test_missing_start_without_skip_download_errors_before_any_subprocess(monkeypatch, tmp_path, capsys):
    calls = _patch_subprocess(monkeypatch)
    rc = _run(monkeypatch, ["--bars-file", str(tmp_path / "bars.json")])

    assert rc == 2
    assert calls == []
    assert "--start is required" in capsys.readouterr().err


def test_request_delay_seconds_and_output_paths_are_forwarded(monkeypatch, tmp_path):
    calls = _patch_subprocess(monkeypatch, returncodes=[0, 0])
    model_out = tmp_path / "model.json"
    report_out = tmp_path / "report.json"

    _run(monkeypatch, [
        "--start", "2026-07-01", "--bars-file", str(tmp_path / "bars.json"),
        "--request-delay-seconds", "0.75", "--output-model", str(model_out), "--output-report", str(report_out),
        "--min-edge", "0.08", "--fee-pct", "0.01", "--slippage-pct", "0.02", "--n-folds", "3",
    ])

    download_argv, backtest_argv = calls
    assert "--request-delay-seconds" in download_argv and "0.75" in download_argv
    assert "--output-model" in backtest_argv and str(model_out) in backtest_argv
    assert "--output-report" in backtest_argv and str(report_out) in backtest_argv
    assert "--min-edge" in backtest_argv and "0.08" in backtest_argv
    assert "--fee-pct" in backtest_argv and "0.01" in backtest_argv
    assert "--slippage-pct" in backtest_argv and "0.02" in backtest_argv
    assert "--n-folds" in backtest_argv and "3" in backtest_argv

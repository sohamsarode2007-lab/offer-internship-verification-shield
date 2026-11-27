import importlib.util
from pathlib import Path


EVAL_PATH = Path(__file__).resolve().parents[1] / "eval" / "run_eval.py"
SPEC = importlib.util.spec_from_file_location("synthetic_eval_runner", EVAL_PATH)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_report_shows_ec08_label_and_expected_band_separately(capsys, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "0")
    results = runner.evaluate(runner.load_cases())
    runner.report(results)
    output = capsys.readouterr().out
    line = next(line for line in output.splitlines() if line.startswith("EC08"))
    assert "scam" in line and "ABSTENTION" in line
    assert line.count("insufficient evidence, verify manually") == 2
    assert line.rstrip().endswith("PASS")
    assert "expected-vs-actual" in output


def _row(case_id, truth, band):
    return {"case_id": case_id, "case_type": "t", "truth": truth, "predicted_band": band, "expected_band": band}


def test_a_new_dangerous_miss_fails_the_run_but_the_known_one_does_not(capsys):
    legit_band = runner.BANDS[0]
    assert runner.report([_row("EC41", "scam", legit_band)]) is True          # documented limit stays visible, not fatal
    assert runner.report([_row("EC99", "scam", legit_band)]) is False         # any other scam rated legitimate fails
    assert "new dangerous miss" in capsys.readouterr().out

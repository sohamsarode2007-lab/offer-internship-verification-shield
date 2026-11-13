import importlib.util
from pathlib import Path


EVAL_PATH = Path(__file__).resolve().parents[1] / "eval" / "run_eval.py"
SPEC = importlib.util.spec_from_file_location("synthetic_eval_runner", EVAL_PATH)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_report_shows_ec08_label_and_expected_band_separately(capsys, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "0")
    monkeypatch.setenv("DEMO_REGISTRY_FIXTURES", "")
    results = runner.evaluate(runner.load_cases())
    runner.report(results)
    output = capsys.readouterr().out
    line = next(line for line in output.splitlines() if line.startswith("EC08"))
    assert "scam" in line and "ABSTENTION" in line
    assert line.count("insufficient evidence, verify manually") == 2
    assert line.rstrip().endswith("PASS")
    assert "expected-vs-actual" in output

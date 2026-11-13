import importlib.util
from pathlib import Path


EVAL_PATH = Path(__file__).resolve().parents[1] / "eval" / "run_eval.py"
SPEC = importlib.util.spec_from_file_location("synthetic_eval_runner", EVAL_PATH)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_report_separates_label_miss_from_expected_band_pass(capsys):
    runner.report([{
        "case_id": "EC08",
        "case_type": "soft_urgency",
        "truth": "scam",
        "predicted_band": "likely legitimate",
        "expected_band": "likely legitimate",
    }])
    output = capsys.readouterr().out
    assert "EC08" in output
    assert "DANGEROUS MISS" in output
    assert "expected-vs-actual" in output
    assert "PASS" in output

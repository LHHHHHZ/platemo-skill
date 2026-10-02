# -*- coding: utf-8 -*-
"""验证无效最终指标和不完整比较不会产生可用于迭代的结论。"""

import contextlib
import io
import json
import sys
import unittest
from unittest.mock import patch

import numpy as np
from scipy.io import savemat

import test_experiment_isolation as fixtures


class MetricValidationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExperimentIsolationTests(methodName="runTest")
        self.fixture.setUp()
        self.root = self.fixture.root

    def tearDown(self):
        self.fixture.tearDown()

    def make_experiment(self, name="data", runs=3, algorithms=None):
        return self.fixture.make_experiment(name, runs=runs, algorithms=algorithms)

    def replace_result(self, path, data, index, metrics=None, content=None):
        record = data["records"][index]
        result = path.parent / record["file"]
        if content is not None:
            result.write_bytes(content)
        else:
            savemat(result, {"metric": metrics})
        record["sha256"] = fixtures.file_hash(result)
        self.fixture.rewrite(path, data)

    def run_parser(self, *args):
        output = self.root / "metrics.json"
        stdout, stderr = io.StringIO(), io.StringIO()
        argv = [str(fixtures.SCRIPTS / "parse_results.py"), *map(str, args), "--json", str(output)]
        with patch.object(sys, "argv", argv), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = fixtures.parser.main()
        payload = json.loads(output.read_text(encoding="utf-8"))
        return code, payload, stdout.getvalue(), stderr.getvalue()

    def assert_insufficient(self, result, issue):
        code, payload, stdout, stderr = result
        self.assertEqual(code, 2)
        self.assertEqual(payload["status"], "insufficient_evidence")
        self.assertFalse(payload["can_iterate"])
        self.assertFalse(payload["comparison_ready"])
        self.assertEqual(payload["tests"], [])
        self.assertTrue(all("is_best" not in row for row in payload["rows"]))
        self.assertIn(issue, {item["code"] for item in payload["validation"]["issues"]})
        self.assertIn("INSUFFICIENT_EVIDENCE", stderr)

    def test_final_value_never_falls_back_to_earlier_generation(self):
        for value in [np.nan, np.inf, -np.inf]:
            with self.subTest(value=value):
                self.assertIsNone(fixtures.parser.final_value([0.9, 0.5, value]))
        self.assertEqual(fixtures.parser.final_value([np.nan, 0.5]), 0.5)
        self.assertEqual(fixtures.parser.final_value(np.array([[0.9, 0.5]])), 0.5)
        self.assertEqual(fixtures.parser.final_value(np.array([[0.9], [0.5]])), 0.5)
        self.assertEqual(fixtures.parser.final_value(0.5), 0.5)

    def test_empty_and_malformed_metrics_are_rejected(self):
        for value in [[], None, "0.5", [True], [1 + 2j], [[1, 2], [3, 4]], np.zeros((2, 2, 2))]:
            with self.subTest(value=str(value)):
                self.assertIsNone(fixtures.parser.final_value(value))

    def test_non_finite_final_value_blocks_comparison_and_names_run(self):
        path, data = self.make_experiment()
        self.replace_result(path, data, 1, {"IGD": [0.9, 0.5, np.nan], "HV": 0.5})
        result = self.run_parser("--manifest", path)
        self.assert_insufficient(result, "invalid_final_metric")
        self.assertEqual(result[2], "")
        issue = next(item for item in result[1]["validation"]["issues"] if item["code"] == "invalid_final_metric")
        self.assertEqual((issue["algorithm"], issue["problem"], issue["metric"], issue["run"]),
                         ("NSGAII", "LSMOP1", "IGD", 2))
        igd = next(row for row in result[1]["rows"] if row["metric"] == "IGD")
        self.assertEqual((igd["n"], igd["mean"]), (2, 2.0))

    def test_infinity_empty_string_and_complex_metrics_block_cli(self):
        for name, value in [("inf", np.inf), ("empty", []), ("text", "bad"), ("complex", 1 + 2j)]:
            path, data = self.make_experiment(name)
            self.replace_result(path, data, 0, {"IGD": value, "HV": 0.5})
            self.assert_insufficient(self.run_parser("--manifest", path), "invalid_final_metric")

    def test_missing_requested_metric_blocks_otherwise_valid_report(self):
        path, data = self.make_experiment()
        self.replace_result(path, data, 0, {"IGD": 1.0})
        self.assert_insufficient(self.run_parser("--manifest", path), "missing_metric")

    def test_one_run_is_insufficient_and_std_is_unknown(self):
        path, _ = self.make_experiment(runs=1)
        result = self.run_parser("--manifest", path)
        self.assert_insufficient(result, "insufficient_runs")
        self.assertTrue(all(row["std"] is None for row in result[1]["rows"]))

    def test_user_can_raise_minimum_valid_runs(self):
        path, _ = self.make_experiment()
        self.assert_insufficient(self.run_parser("--manifest", path, "--min-runs", 5), "insufficient_runs")

    def test_preview_shows_partial_data_without_ranking_and_still_fails(self):
        path, _ = self.make_experiment(runs=1)
        result = self.run_parser("--manifest", path, "--preview")
        self.assert_insufficient(result, "insufficient_runs")
        self.assertIn("PREVIEW ONLY", result[2])
        self.assertIn("n/a (n=1)", result[2])
        self.assertNotIn("*", result[2])
        self.assertTrue(result[1]["validation"]["preview"])

    def test_valid_preview_never_enables_iteration(self):
        algorithms = [{"class": "NSGAII", "params": []}, {"class": "NSGAIII", "params": []}]
        path, _ = self.make_experiment(algorithms=algorithms)
        code, payload, stdout, _ = self.run_parser("--manifest", path, "--baseline", "NSGAIII", "--preview")
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "ready")
        self.assertFalse(payload["can_iterate"])
        self.assertFalse(payload["comparison_ready"])
        self.assertEqual(payload["tests"], [])
        self.assertIn("PREVIEW ONLY", stdout)

    def test_missing_baseline_writes_failure_report(self):
        path, _ = self.make_experiment()
        self.assert_insufficient(self.run_parser("--manifest", path, "--baseline", "NSGAIII"), "baseline_missing")

    def test_baseline_must_cover_every_problem(self):
        base, _ = self.make_experiment("base", algorithms=[{"class": "NSGAIII", "params": []}])
        candidate, data = self.make_experiment("candidate")
        data["config"]["problems"][0]["class"] = "LSMOP2"
        for record in data["records"]:
            old = candidate.parent / record["file"]
            record["problem"] = "LSMOP2"
            record["file"] = record["file"].replace("LSMOP1", "LSMOP2")
            old.rename(candidate.parent / record["file"])
        self.fixture.rewrite(candidate, data)
        result = self.run_parser("--experiment", f"base={base}", "--experiment", f"new={candidate}",
                                 "--baseline", "base/NSGAIII")
        self.assert_insufficient(result, "baseline_missing")
        self.assertIn("series_missing", {item["code"] for item in result[1]["validation"]["issues"]})

    def test_baseline_metric_must_be_valid(self):
        algorithms = [{"class": "NSGAII", "params": []}, {"class": "NSGAIII", "params": []}]
        path, data = self.make_experiment(algorithms=algorithms)
        for index in range(3, 6):
            self.replace_result(path, data, index, {"IGD": 1.0, "HV": np.nan})
        self.assert_insufficient(self.run_parser("--manifest", path, "--baseline", "NSGAIII"),
                                 "baseline_metric_missing")

    def test_unreadable_metric_file_cannot_be_silently_skipped(self):
        path, data = self.make_experiment()
        self.replace_result(path, data, 0, content=b"not a MATLAB file")
        self.assert_insufficient(self.run_parser("--manifest", path), "unreadable_result")

    def test_failed_report_overwrites_stale_success_report(self):
        path, _ = self.make_experiment()
        previous = self.root / "metrics.json"
        previous.write_text('{"status":"ready","can_iterate":true}', encoding="utf-8")
        self.assert_insufficient(self.run_parser("--manifest", path, "--min-runs", 5), "insufficient_runs")
        self.assertFalse(json.loads(previous.read_text(encoding="utf-8"))["can_iterate"])

    def test_zero_valid_metrics_and_source_errors_write_diagnostics(self):
        path, data = self.make_experiment()
        for index in range(3):
            self.replace_result(path, data, index, {})
        self.assert_insufficient(self.run_parser("--manifest", path), "no_valid_metrics")
        self.assert_insufficient(self.run_parser("--manifest", self.root / "absent.json"), "source_validation_failed")
        self.assert_insufficient(self.run_parser("--manifest", path, "--metrics", "GD"), "source_validation_failed")

    def test_valid_comparison_retains_statistics_and_enables_iteration(self):
        algorithms = [{"class": "NSGAII", "params": []}, {"class": "NSGAIII", "params": []}]
        path, _ = self.make_experiment(algorithms=algorithms)
        code, payload, stdout, _ = self.run_parser("--manifest", path, "--baseline", "NSGAIII")
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "ready")
        self.assertTrue(payload["comparison_ready"])
        self.assertTrue(payload["can_iterate"])
        self.assertEqual(payload["validation"]["issues"], [])
        self.assertEqual(len(payload["tests"]), 2)
        self.assertIn("n=3", stdout)

    def test_statistics_without_baseline_do_not_enable_iteration(self):
        path, _ = self.make_experiment()
        code, payload, _, _ = self.run_parser("--manifest", path)
        self.assertEqual(code, 0)
        self.assertFalse(payload["comparison_ready"])
        self.assertFalse(payload["can_iterate"])

    def test_legacy_preview_catches_duplicate_runs_and_missing_baseline(self):
        path, data = self.make_experiment()
        # 历史 series 的目录名必须与算法类名一致。
        folder = self.root / "NSGAII"
        folder.mkdir()
        for record in data["records"]:
            original = path.parent / record["file"]
            (folder / original.name).write_bytes(original.read_bytes())
        result = self.run_parser("--series", f"a={folder}", "--series", f"a={folder}", "--allow-legacy")
        self.assert_insufficient(result, "duplicate_run")
        result = self.run_parser("--series", f"a={folder}", "--allow-legacy", "--baseline", "missing")
        self.assert_insufficient(result, "baseline_missing")

    def test_invalid_summary_is_reported_as_insufficient_evidence(self):
        path, data = self.make_experiment()
        for index in range(3):
            self.replace_result(path, data, index, {"IGD": 1e308, "HV": 0.5})
        result = self.run_parser("--manifest", path, "--preview")
        self.assert_insufficient(result, "invalid_summary")
        json.dumps(result[1], allow_nan=False)

    def test_cli_validates_minimum_alpha_and_duplicate_metric_names(self):
        path, _ = self.make_experiment()
        for args in [("--min-runs", 1), ("--alpha", "nan"), ("--alpha", 1),
                     ("--metrics", ""), ("--metrics", "IGD,IGD")]:
            completed = self.fixture.cli("--manifest", path, *args)
            self.assertEqual(completed.returncode, 2)


if __name__ == "__main__":
    unittest.main()

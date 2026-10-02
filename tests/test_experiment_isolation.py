# -*- coding: utf-8 -*-
"""实验隔离的回归测试，不依赖 MATLAB 或真实算法数据。"""

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from scipy.io import savemat

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/platemo/scripts"
sys.path.insert(0, str(SCRIPTS))
from experiment_manifest import canonical, experiment_files, file_hash, load_manifest, params, source_signature

spec = importlib.util.spec_from_file_location("parse_results", SCRIPTS / "parse_results.py")
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)


class ExperimentIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="platemo-isolation-")
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def make_experiment(self, name, runs=3, algorithms=None, **config_overrides):
        folder = self.root / name
        folder.mkdir()
        algorithms = algorithms or [{"class": "SET_NSGAIII", "params": []}]
        config = {"algorithms": algorithms,
                  "problems": [{"class": "LSMOP1", "M": 3, "D": 500, "params": []}],
                  "N": 100, "maxFE": 100000, "runs": runs,
                  "metrics": ["IGD", "HV"], "save_count": 6}
        config.update(config_overrides)
        sources = [{"path": "fixture.m", "sha256": "fixture-source"}]
        records = []
        for index, algorithm in enumerate(algorithms):
            label = algorithm.get("label", algorithm["class"])
            case = folder / "Data" / str(index)
            case.mkdir(parents=True)
            for run in range(1, runs + 1):
                filename = f"{algorithm['class']}_LSMOP1_M3_D500_{run}.mat"
                result = case / filename
                savemat(result, {"metric": {"IGD": float(run), "HV": 0.5}})
                records.append({"experiment_id": name, "algorithm": algorithm["class"], "label": label,
                                "algorithm_params": params(algorithm), "algorithm_sources": sources,
                                "problem": "LSMOP1", "problem_params": params(config["problems"][0]),
                                "problem_sources": sources, "problem_index": 1, "run": run,
                                "requested_N": config["N"], "maxFE": config["maxFE"],
                                "M": 3, "D": 500, "actual_N": 91, "actual_FE": config["maxFE"],
                                "status": "ok", "file": result.relative_to(folder).as_posix(),
                                "sha256": file_hash(result)})
        manifest = {"schema_version": 1, "experiment_id": name, "status": "completed", "config": config,
                    "platform_sources": sources, "expected_runs": len(records), "records": records}
        path = folder / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path, manifest

    def args(self, manifest=None, experiments=None, **overrides):
        args = SimpleNamespace(manifest=manifest, experiment=experiments or [], algorithms="", problems="",
                               metrics="IGD,HV", baseline="", allow_legacy=False, data_dir=None, series=[])
        for name, value in overrides.items():
            setattr(args, name, value)
        return args

    def rewrite(self, path, manifest):
        path.write_text(json.dumps(manifest), encoding="utf-8")

    def cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / "parse_results.py"), *map(str, args)],
                              capture_output=True, text=True, encoding="utf-8")

    def test_three_new_runs_do_not_include_ten_old_runs(self):
        old, _ = self.make_experiment("old", runs=10)
        new, _ = self.make_experiment("new", runs=3)
        args = self.args(new)
        rows = parser.summarize(parser.collect(args))
        self.assertEqual({row["n"] for row in rows}, {3})
        self.assertEqual(rows[0]["mean"], 2.0)
        compared, _ = experiment_files(self.args(experiments=[f"old={old}", f"new={new}"]))
        self.assertEqual(sum(label == "old/SET_NSGAIII" for label, _, _ in compared), 10)
        self.assertEqual(sum(label == "new/SET_NSGAIII" for label, _, _ in compared), 3)

    def test_unlisted_file_is_ignored(self):
        path, data = self.make_experiment("new")
        result = path.parent / data["records"][0]["file"]
        savemat(result.with_name("SET_NSGAIII_LSMOP1_M3_D500_99.mat"), {"metric": {"IGD": 999.0}})
        self.assertEqual(len(experiment_files(self.args(path))[0]), 3)

    def test_variants_of_same_class_keep_separate_labels(self):
        algorithms = [{"class": "SET_NSGAIII", "label": "inference", "params": [0, 20]},
                      {"class": "SET_NSGAIII", "label": "online", "params": [2, 20]}]
        path, _ = self.make_experiment("variants", algorithms=algorithms)
        rows = parser.summarize(parser.collect(self.args(path)))
        self.assertEqual({row["algorithm"] for row in rows}, {"inference", "online"})
        self.assertEqual({row["n"] for row in rows}, {3})

    def test_protocol_mismatches_are_rejected(self):
        first, _ = self.make_experiment("base")
        for field, value in [("N", 200), ("maxFE", 200000), ("save_count", 8),
                             ("problems", [{"class": "LSMOP1", "M": 3, "D": 500, "params": [0.2]}])]:
            with self.subTest(field=field):
                other, _ = self.make_experiment(field, **{field: value})
                with self.assertRaisesRegex(ValueError, "Incompatible comparison protocol"):
                    experiment_files(self.args(experiments=[f"a={first}", f"b={other}"]))

    def test_problem_and_metric_source_mismatches_are_rejected(self):
        base, _ = self.make_experiment("base")
        for field in ["problem_sources", "platform_sources"]:
            path, data = self.make_experiment(field)
            if field == "platform_sources":
                data[field][0]["sha256"] = "changed"
            else:
                for record in data["records"]:
                    record[field] = [{"path": "fixture.m", "sha256": "changed"}]
            self.rewrite(path, data)
            with self.assertRaisesRegex(ValueError, "Incompatible comparison protocol"):
                experiment_files(self.args(experiments=[f"a={base}", f"b={path}"]))

    def test_corrupt_missing_and_external_result_files_are_rejected(self):
        for mode in ["corrupt", "missing", "outside", "metadata"]:
            path, data = self.make_experiment(mode)
            record = data["records"][0]
            result = path.parent / record["file"]
            if mode == "corrupt":
                result.write_bytes(b"changed")
            elif mode == "missing":
                result.unlink()
            elif mode == "outside":
                record["file"] = "../external.mat"
                self.rewrite(path, data)
            else:
                record["M"] = 4
                self.rewrite(path, data)
            with self.assertRaises(ValueError):
                load_manifest(path)

    def test_incomplete_duplicate_and_mixed_runs_are_rejected(self):
        for mode in ["missing", "duplicate", "failed", "version", "params", "count", "schema", "running"]:
            path, data = self.make_experiment(mode)
            if mode == "missing":
                data["records"].pop()
            elif mode == "duplicate":
                data["records"].append(copy.deepcopy(data["records"][0]))
            elif mode == "version":
                data["records"][0]["algorithm_sources"] = [{"path": "fixture.m", "sha256": "changed"}]
            elif mode == "params":
                data["records"][0]["algorithm_params"] = [2]
            elif mode == "count":
                data["expected_runs"] = 99
            elif mode == "schema":
                data["schema_version"] = 2
            elif mode == "running":
                data["status"] = "running"
            else:
                data["records"][0]["status"] = "failed"
            self.rewrite(path, data)
            with self.assertRaises(ValueError):
                load_manifest(path)

    def test_source_helpers(self):
        self.assertEqual(params({}), [])
        self.assertEqual(params({"params": [0]}), [0])
        self.assertEqual(params({"params": 0}), 0)
        self.assertEqual(canonical({"b": 2, "a": 1}), canonical({"a": 1, "b": 2}))
        self.assertEqual(source_signature([{"path": "b", "sha256": "2"}, {"path": "a", "sha256": "1"}]),
                         [("a", "1"), ("b", "2")])

    def test_cli_json_contains_selected_provenance(self):
        path, _ = self.make_experiment("new")
        output = self.root / "summary.json"
        completed = self.cli("--manifest", path, "--json", output)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        data = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(data["provenance_verified"])
        self.assertEqual(len(data["experiments"][0]["records"]), 3)

    def test_legacy_requires_explicit_opt_in(self):
        folder = self.root / "legacy" / "SET_NSGAIII"
        folder.mkdir(parents=True)
        savemat(folder / "SET_NSGAIII_LSMOP1_M3_D500_1.mat", {"metric": {"IGD": 1.0, "HV": 0.5}})
        denied = self.cli("--data-dir", folder.parent)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("--allow-legacy", denied.stderr)
        allowed = self.cli("--data-dir", folder.parent, "--allow-legacy")
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertIn("unverified", allowed.stderr)

    def test_invalid_selection_is_rejected(self):
        path, _ = self.make_experiment("new")
        cases = [self.args(path, baseline="missing"), self.args(path, metrics="GD"),
                 self.args(experiments=["missing-equals"]), self.args(experiments=[f"a={path}", f"a={path}"]),
                 self.args(experiments=[f"={path}"]), self.args(experiments=[f"a/b={path}"]),
                 self.args(experiments=[f"a={path}", f"b={path}"])]
        for args in cases:
            with self.assertRaises(ValueError):
                experiment_files(args)

    def test_filters_select_exact_algorithm_and_problem(self):
        path, _ = self.make_experiment("new", algorithms=[{"class": "SET_NSGAIII", "params": []},
                                                         {"class": "NSGAIII", "params": []}])
        rows, provenance = experiment_files(self.args(experiments=[f"new={path}"], algorithms="new/NSGAIII"))
        self.assertEqual(len(rows), 3)
        self.assertEqual({label for label, _, _ in rows}, {"new/NSGAIII"})
        self.assertEqual(len(provenance[0]["records"]), 3)
        self.assertEqual(experiment_files(self.args(path, problems="LSMOP2"))[0], [])


if __name__ == "__main__":
    unittest.main()

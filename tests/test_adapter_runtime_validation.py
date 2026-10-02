# -*- coding: utf-8 -*-
"""真实调用路径的替身测试，以及运行机制证据对比较/迭代的门槛测试。"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import test_experiment_isolation as fixtures
from adapters.set_nsgaiii.runtime import start, diagnostic_issues, weight_hash


def model_module(weight_path=None, loaded=False, invalid=None, error=None):
    module = SimpleNamespace(_MODEL_CACHE={})

    def clear_model_cache():
        module._MODEL_CACHE.clear()

    def get_model(name, dim_input, num_outputs, dim_output, pop_m, train_mode=1):
        if error:
            raise RuntimeError(error)
        model = object()
        module._MODEL_CACHE["fixture"] = {"model": model, "train_mode": train_mode,
            "pretrained_loaded": loaded, "weight_path": weight_path, "device": "cpu",
            "metadata": {"feature_norm": "per-gen"}, "finetune_scope": "decoder"}
        return model, object(), "cpu"

    def online_train_and_predict(name, dim_input, num_outputs, dim_output, X_train=None,
                                 train_steps=0, X_pred=None, current_FE=0, pop_m=3,
                                 train_mode=1, dataset_tag=None, pretrained_tag=None):
        module.get_model(name, dim_input, num_outputs, dim_output, pop_m, train_mode)
        for _ in range(train_steps):
            module.train_step()
        return invalid if invalid is not None else np.ones((1, num_outputs, dim_output))

    module.clear_model_cache = clear_model_cache
    module.get_model = get_model
    module.online_train_and_predict = online_train_and_predict
    module.train_step = lambda: 0.5
    return module


class RuntimeMonitorTests(unittest.TestCase):
    def test_online_predictions_preserve_original_result_and_restore_functions(self):
        module = model_module()
        originals = (module.get_model, module.online_train_and_predict, module.clear_model_cache)
        monitor = start(module, 2)
        module.clear_model_cache()
        result = module.online_train_and_predict("a", 8, 6, 4, train_mode=2)
        self.assertEqual(result.shape, (1, 6, 4))
        data = json.loads(monitor.snapshot_json())
        self.assertEqual((data["cache_reset_calls"], data["prediction_successes"], data["predicted_solutions"]), (1, 1, 6))
        self.assertEqual(data["models"][0]["actual_mode"], 2)
        self.assertEqual(data["issues"], [])
        monitor.close()
        monitor.close()
        self.assertEqual((module.get_model, module.online_train_and_predict, module.clear_model_cache), originals)

    def test_finetuning_fallback_is_detected_before_prediction(self):
        module = model_module()
        monitor = start(module, 1)
        with self.assertRaisesRegex(RuntimeError, "Actual training mode"):
            module.online_train_and_predict("a", 8, 6, 4, train_mode=1)
        data = json.loads(monitor.snapshot_json())
        self.assertEqual(data["models"][0]["actual_mode"], 2)
        self.assertEqual((data["prediction_successes"], data["prediction_failures"]), (0, 1))
        self.assertIn("training_mode_mismatch", {item["code"] for item in data["issues"]})
        monitor.close()

    def test_inference_cannot_continue_without_weights(self):
        module = model_module()
        monitor = start(module, 0)
        with self.assertRaisesRegex(RuntimeError, "Pretrained weights"):
            module.online_train_and_predict("a", 8, 6, 4, train_mode=0)
        self.assertIn("pretrained_weights_missing", {item["code"] for item in monitor.data["issues"]})

    def test_loaded_weights_are_hashed_in_actual_modes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "weights.pth"
            path.write_bytes(b"test-weights")
            for mode in (0, 1):
                module = model_module(str(path), True)
                monitor = start(module, mode)
                module.online_train_and_predict("a", 8, 6, 4, train_mode=mode)
                model = monitor.data["models"][0]
                self.assertEqual(model["weight_sha256"], weight_hash(path))
                self.assertEqual(model["actual_mode"], mode)

    def test_nonfinite_empty_and_wrong_shape_outputs_are_rejected(self):
        for invalid in (np.full((1, 6, 4), np.nan), np.full((1, 6, 4), np.inf), np.empty((1, 0, 4)), np.ones((6, 4))):
            with self.subTest(shape=invalid.shape):
                module = model_module(invalid=invalid)
                monitor = start(module, 2)
                with self.assertRaisesRegex(RuntimeError, "Invalid prediction"):
                    module.online_train_and_predict("a", 8, 6, 4, train_mode=2)
                self.assertEqual(monitor.data["prediction_failures"], 1)

    def test_model_exception_is_recorded_and_propagated(self):
        module = model_module(error="model unavailable")
        monitor = start(module, 2)
        with self.assertRaisesRegex(RuntimeError, "model unavailable"):
            module.online_train_and_predict("a", 8, 6, 4, train_mode=2)
        self.assertIn("model_initialization_failed", {item["code"] for item in monitor.data["issues"]})

    def test_initialization_exception_is_recorded_and_interfaces_restored(self):
        module = model_module()
        def failed_reset():
            raise RuntimeError("cache reset failed")
        module.clear_model_cache = failed_reset
        monitor = start(module, 2)
        with self.assertRaisesRegex(RuntimeError, "cache reset failed"):
            module.clear_model_cache()
        self.assertEqual(monitor.data["cache_reset_calls"], 0)
        self.assertEqual(monitor.data["issues"][0]["code"], "python_initialization_failed")
        monitor.close()
        self.assertIs(module.clear_model_cache, failed_reset)

    def test_unverifiable_model_cache_cannot_silently_pass(self):
        module = model_module()
        module.get_model = lambda *args, **kwargs: (object(), None, "cpu")
        monitor = start(module, 2)
        with self.assertRaisesRegex(RuntimeError, "Cannot verify"):
            module.online_train_and_predict("a", 8, 6, 4, train_mode=2)
        self.assertEqual(monitor.data["prediction_successes"], 0)

    def test_wrong_requested_mode_is_rejected(self):
        module = model_module()
        monitor = start(module, 2)
        with self.assertRaisesRegex(RuntimeError, "expected 2"):
            module.online_train_and_predict("a", 8, 6, 4, train_mode=1)
        self.assertEqual(monitor.data["model_calls"], 0)

    def test_training_steps_preserve_loss_and_inference_forbids_training(self):
        module = model_module()
        original = module.train_step
        monitor = start(module, 2)
        self.assertEqual(module.train_step(), 0.5)
        self.assertEqual(monitor.data["training_steps"], 1)
        monitor.close()
        self.assertIs(module.train_step, original)
        monitor = start(module, 0)
        with self.assertRaisesRegex(RuntimeError, "must not perform"):
            module.train_step()

    def test_restarting_monitor_does_not_stack_wrappers(self):
        module = model_module()
        original = module.get_model
        first = start(module, 2)
        second = start(module, 2)
        module.online_train_and_predict("a", 8, 6, 4, train_mode=2)
        self.assertEqual(first.data["prediction_attempts"], 0)
        self.assertEqual(second.data["prediction_attempts"], 1)
        second.close()
        self.assertIs(module.get_model, original)

    def test_unsupported_interface_and_invalid_modes_are_rejected(self):
        for mode in (-1, 3, 2.5, True):
            with self.assertRaises(ValueError):
                start(model_module(), mode)
        module = model_module()
        module._MODEL_CACHE = []
        with self.assertRaises(ValueError):
            start(module, 2)
        module = model_module()
        module.train_step = None
        with self.assertRaisesRegex(ValueError, "callable interface"):
            start(module, 2)


class RuntimeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExperimentIsolationTests(methodName="runTest")
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_valid_modes_and_zero_survivors_are_accepted(self):
        for mode in (0, 1, 2):
            path, data = self.fixture.make_experiment(str(mode), algorithms=[{"class": "SET_NSGAIII", "params": [mode, 20]}])
            self.assertEqual(diagnostic_issues(data["records"][0]), [])

    def test_missing_or_failed_diagnostics_block_even_finite_metrics(self):
        for kind in ("missing", "failed", "not_exercised", "ga_fallback", "no_injection", "mode", "weight", "counter", "init", "no_training"):
            with self.subTest(kind=kind):
                path, data = self.fixture.make_experiment(kind, algorithms=[{"class": "SET_NSGAIII", "params": []}, {"class": "NSGAIII", "params": []}])
                record = data["records"][0]
                diag = record["runtime_diagnostics"]
                if kind == "missing": del record["runtime_diagnostics"]
                elif kind in ("failed", "not_exercised"): diag["status"] = kind
                elif kind == "ga_fallback": diag["ga_fallbacks"] = 1
                elif kind == "no_injection": diag["injected_solutions"] = 0
                elif kind == "mode": diag["models"][0]["actual_mode"] = 2
                elif kind == "weight": diag["models"][0]["weight_sha256"] = "unverified"
                elif kind == "counter": diag["prediction_successes"] = -1
                elif kind == "init": diag["python_ready"] = False
                elif kind == "no_training": diag["training_steps"] = 0
                self.fixture.rewrite(path, data)
                output = path.parent / "metrics.json"
                result = self.fixture.cli("--manifest", path, "--baseline", "NSGAIII", "--json", output)
                payload = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(result.returncode, 2)
                self.assertFalse(payload["can_iterate"])
                self.assertEqual(payload["tests"], [])
                self.assertTrue(any(item["code"].startswith("runtime_") for item in payload["validation"]["issues"]))

    def test_malformed_diagnostics_are_errors_not_crashes(self):
        path, data = self.fixture.make_experiment("malformed", algorithms=[{"class": "SET_NSGAIII"}])
        record = data["records"][0]
        for diag in ({}, {"status": "passed"}, [], None):
            record["runtime_diagnostics"] = diag
            self.assertTrue(diagnostic_issues(record))

    def test_generic_algorithms_do_not_require_set_diagnostics(self):
        self.assertEqual(diagnostic_issues({"algorithm": "NSGAIII"}), [])


if __name__ == "__main__":
    unittest.main()

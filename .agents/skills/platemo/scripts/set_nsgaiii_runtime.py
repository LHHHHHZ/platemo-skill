# -*- coding: utf-8 -*-
"""临时监测 SET-NSGAIII 的真实 Python 调用，运行结束后恢复原接口。"""

import functools
import hashlib
import inspect
import json
from pathlib import Path

import numpy as np


def weight_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RuntimeMonitor:
    def __init__(self, module, expected_mode):
        if isinstance(expected_mode, bool) or expected_mode not in (0, 1, 2):
            raise ValueError("TRAIN must be 0, 1 or 2")
        self.module = module
        self.expected_mode = int(expected_mode)
        self.originals = {name: getattr(module, name) for name in
                          ("get_model", "online_train_and_predict", "clear_model_cache", "train_step")}
        if not all(callable(value) for value in self.originals.values()):
            raise ValueError("Unsupported SetTransformer callable interface")
        if not isinstance(module._MODEL_CACHE, dict):
            raise ValueError("Unsupported SetTransformer model cache contract")
        self.data = {"schema_version": 1, "adapter": "SET_NSGAIII", "requested_mode": self.expected_mode,
                     "cache_reset_calls": 0, "model_calls": 0, "prediction_attempts": 0,
                     "prediction_successes": 0, "prediction_failures": 0, "predicted_solutions": 0,
                     "training_steps": 0,
                     "models": [], "issues": []}
        self.model_ids = set()
        self.wrappers = {}
        for name, handler in {"get_model": self._get_model, "online_train_and_predict": self._predict,
                              "clear_model_cache": self._clear, "train_step": self._train}.items():
            def make_wrapper(original, bound_handler):
                @functools.wraps(original)
                def wrapper(*args, **kwargs):
                    return bound_handler(*args, **kwargs)
                return wrapper
            self.wrappers[name] = make_wrapper(self.originals[name], handler)
            setattr(module, name, self.wrappers[name])

    def _issue(self, code, message):
        issue = {"code": code, "message": str(message)}
        if issue not in self.data["issues"]:
            self.data["issues"].append(issue)

    def _clear(self):
        try:
            result = self.originals["clear_model_cache"]()
        except Exception as exc:
            self._issue("python_initialization_failed", exc)
            raise
        self.data["cache_reset_calls"] += 1
        return result

    def _get_model(self, *args, **kwargs):
        self.data["model_calls"] += 1
        try:
            result = self.originals["get_model"](*args, **kwargs)
            model = result[0]
            matches = [entry for entry in self.module._MODEL_CACHE.values() if entry.get("model") is model]
            if len(matches) != 1:
                raise RuntimeError("Cannot verify actual model initialization metadata")
            entry = matches[0]
            requested = int(entry["train_mode"])
            loaded = bool(entry["pretrained_loaded"])
            actual = 2 if requested == 1 and not loaded else requested
            if id(model) not in self.model_ids:
                path = entry.get("weight_path")
                metadata = entry.get("metadata") or {}
                self.data["models"].append({"requested_mode": requested, "actual_mode": actual,
                                            "pretrained_loaded": loaded, "weight_path": path,
                                            "weight_sha256": weight_hash(path) if loaded and path else None,
                                            "device": str(entry["device"]),
                                            "feature_norm": metadata.get("feature_norm"),
                                            "finetune_scope": entry.get("finetune_scope")})
                self.model_ids.add(id(model))
            if requested != self.expected_mode or actual != self.expected_mode:
                self._issue("training_mode_mismatch", f"Expected TRAIN={self.expected_mode}, actual mode={actual}")
                raise RuntimeError("Actual training mode differs from requested experiment")
            if requested in (0, 1) and (not loaded or not entry.get("weight_path")):
                self._issue("pretrained_weights_missing", "Requested pretraining mode has no verified loaded weights")
                raise RuntimeError("Pretrained weights are required for TRAIN=0/1; use TRAIN=2 explicitly for online-only experiments")
            return result
        except Exception as exc:
            self._issue("model_initialization_failed", exc)
            raise

    def _predict(self, *args, **kwargs):
        self.data["prediction_attempts"] += 1
        try:
            bound = inspect.signature(self.originals["online_train_and_predict"]).bind(*args, **kwargs)
            bound.apply_defaults()
            requested = int(bound.arguments["train_mode"])
            if requested != self.expected_mode:
                raise RuntimeError(f"Prediction requested TRAIN={requested}, expected {self.expected_mode}")
            result = self.originals["online_train_and_predict"](*args, **kwargs)
            values = result.detach().cpu().numpy() if hasattr(result, "detach") else np.asarray(result)
            expected = (1, int(bound.arguments["num_outputs"]), int(bound.arguments["dim_output"]))
            if values.shape != expected or values.size == 0 or not np.isfinite(values).all():
                raise RuntimeError(f"Invalid prediction output: expected finite array of shape {expected}")
            self.data["prediction_successes"] += 1
            self.data["predicted_solutions"] += expected[1]
            return result
        except Exception as exc:
            self.data["prediction_failures"] += 1
            self._issue("prediction_failed", exc)
            raise

    def _train(self, *args, **kwargs):
        if self.expected_mode == 0:
            self._issue("unexpected_training", "Inference-only experiment attempted a training step")
            raise RuntimeError("TRAIN=0 must not perform online training")
        result = self.originals["train_step"](*args, **kwargs)
        self.data["training_steps"] += 1
        return result

    def snapshot_json(self):
        return json.dumps(self.data, allow_nan=False)

    def close(self):
        for name, original in self.originals.items():
            if getattr(self.module, name) is self.wrappers[name]:
                setattr(self.module, name, original)
        if getattr(self.module, "_platemo_runtime_monitor", None) is self:
            delattr(self.module, "_platemo_runtime_monitor")


def start(module, expected_mode):
    previous = getattr(module, "_platemo_runtime_monitor", None)
    if previous is not None:
        previous.close()
    monitor = RuntimeMonitor(module, expected_mode)
    module._platemo_runtime_monitor = monitor
    return monitor


def diagnostic_issues(record):
    """比较时核对实际机制证据；历史 SET 结果缺少诊断也不能用于迭代。"""
    if record["algorithm"] != "SET_NSGAIII":
        return []
    diag = record.get("runtime_diagnostics")
    if not isinstance(diag, dict):
        return [{"code": "runtime_diagnostics_missing", "message": "SET_NSGAIII runtime mechanism was not verified."}]
    try:
        configured = record.get("algorithm_params") or []
        expected = configured[0] if configured else 1
        if diag["schema_version"] != 1 or diag["adapter"] != "SET_NSGAIII" or diag["requested_mode"] != expected:
            raise ValueError("Runtime diagnostics do not match configured TRAIN mode")
        if diag["status"] != "passed" or diag["issues"] or not diag["python_ready"]:
            raise ValueError(f"Runtime verification did not pass: {diag['status']}")
        for name in ("cache_reset_calls", "model_calls", "prediction_attempts", "prediction_successes",
                     "prediction_failures", "predicted_solutions", "ga_fallbacks", "injected_batches",
                     "injected_solutions", "training_steps"):
            if type(diag[name]) is not int or diag[name] < 0:
                raise ValueError(f"Invalid runtime counter: {name}")
        if (diag["cache_reset_calls"] < 1 or diag["prediction_successes"] < 1 or diag["prediction_failures"] != 0
                or diag["prediction_attempts"] != diag["prediction_successes"]
                or diag["model_calls"] < 1 or diag["predicted_solutions"] < diag["injected_solutions"]
                or diag["injected_batches"] > diag["prediction_successes"]
                or diag["ga_fallbacks"] != 0 or diag["injected_batches"] < 1 or diag["injected_solutions"] < 1):
            raise ValueError("Missing successful model injection or observed surrogate fallback")
        if (expected not in (0, 1, 2) or (expected == 0 and diag["training_steps"] != 0)
                or (expected in (1, 2) and diag["training_steps"] < 1)):
            raise ValueError("Actual online training steps do not match requested TRAIN mode")
        models = diag["models"]
        if isinstance(models, dict):
            models = [models]
        if not models:
            raise ValueError("Actual model initialization metadata is missing")
        hashes = {item["sha256"] for item in record["algorithm_sources"]}
        for model in models:
            if model["actual_mode"] != expected or model["requested_mode"] != expected:
                raise ValueError("Actual training mode differs from configured TRAIN")
            if expected in (0, 1) and (not model["pretrained_loaded"] or not model["weight_path"]
                                      or model["weight_sha256"] not in hashes):
                raise ValueError("Loaded pretraining weights are not verified by experiment sources")
    except (KeyError, TypeError, ValueError) as exc:
        return [{"code": "runtime_mechanism_invalid", "message": str(exc)}]
    return []

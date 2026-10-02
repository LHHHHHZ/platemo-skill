def passed_diagnostics(mode=1):
    return {"schema_version": 1, "adapter": "SET_NSGAIII", "requested_mode": mode,
            "status": "passed", "python_ready": True, "cache_reset_calls": 1, "model_calls": 2,
            "prediction_attempts": 2, "prediction_successes": 2, "prediction_failures": 0,
            "predicted_solutions": 182, "ga_fallbacks": 0, "injected_batches": 2,
            "injected_solutions": 44, "surviving_solutions": 0, "training_steps": 0 if mode == 0 else 10, "issues": [],
            "models": [{"requested_mode": mode, "actual_mode": mode, "pretrained_loaded": mode != 2,
                        "weight_path": "fixture.pth" if mode != 2 else None,
                        "weight_sha256": "fixture-weight" if mode != 2 else None}]}


def randomness(seed):
    return {'python': {'schema_version': 1, 'seed': seed, 'python_random': True, 'numpy': True,
            'torch_cpu': True, 'torch_cuda': False, 'deterministic_algorithms': True,
            'warn_only': False, 'cudnn_benchmark': False, 'cudnn_deterministic': True,
            'cublas_workspace_config': ':4096:8'}}


def diagnostics(values):
    return passed_diagnostics(values[0] if values else 1)

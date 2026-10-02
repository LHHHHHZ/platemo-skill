# -*- coding: utf-8 -*-
"""控制 SET 的随机流；比较时核对每次运行的 seed 证据。"""
import json
import os
import random

import numpy as np


class RandomStateGuard:
    def __init__(self, torch, seed):
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError("Seed must be an integer between 0 and 2**32-1")
        self.torch = torch
        self.closed = False
        # cuBLAS 配置必须早于 CUDA 初始化；已经初始化的外部会话不能补称可复现。
        workspace = os.environ.get("CUBLAS_WORKSPACE_CONFIG")
        if torch.cuda.is_initialized() and workspace not in (":4096:8", ":16:8"):
            raise RuntimeError("CUDA was initialized without deterministic workspace configuration; start a fresh MATLAB process")
        os.environ["CUBLAS_WORKSPACE_CONFIG"] = workspace if workspace in (":4096:8", ":16:8") else ":4096:8"
        self.python_state = random.getstate()
        self.numpy_state = np.random.get_state()
        self.cpu_state = torch.get_rng_state()
        self.cuda_states = torch.cuda.get_rng_state_all() if torch.cuda.is_available() else []
        self.deterministic = torch.are_deterministic_algorithms_enabled()
        self.warn_only = torch.is_deterministic_algorithms_warn_only_enabled()
        self.benchmark = torch.backends.cudnn.benchmark
        self.cudnn_deterministic = torch.backends.cudnn.deterministic
        try:
            random.seed(int(seed))
            np.random.seed(int(seed))
            torch.manual_seed(int(seed))
            if self.cuda_states:
                torch.cuda.manual_seed_all(int(seed))
            torch.use_deterministic_algorithms(True, warn_only=False)
            torch.backends.cudnn.benchmark = False
            torch.backends.cudnn.deterministic = True
        except Exception:
            self.close()
            raise
        self.info = {"schema_version": 1, "seed": int(seed), "python_random": True, "numpy": True,
                     "torch_cpu": True, "torch_cuda": bool(self.cuda_states),
                     "deterministic_algorithms": True, "warn_only": False,
                     "cudnn_benchmark": False, "cudnn_deterministic": True,
                     "cublas_workspace_config": os.environ["CUBLAS_WORKSPACE_CONFIG"],
                     "torch_version": str(torch.__version__), "cuda_version": torch.version.cuda,
                     "cuda_devices": [torch.cuda.get_device_name(index) for index in range(len(self.cuda_states))],
                     "cudnn_version": torch.backends.cudnn.version()}

    def info_json(self):
        return json.dumps(self.info, allow_nan=False)

    def close(self):
        if self.closed:
            return
        self.closed = True
        random.setstate(self.python_state)
        np.random.set_state(self.numpy_state)
        self.torch.set_rng_state(self.cpu_state)
        if self.cuda_states:
            self.torch.cuda.set_rng_state_all(self.cuda_states)
        self.torch.use_deterministic_algorithms(self.deterministic, warn_only=self.warn_only)
        self.torch.backends.cudnn.benchmark = self.benchmark
        self.torch.backends.cudnn.deterministic = self.cudnn_deterministic
        # 保留进程级 cuBLAS 配置，供同一 MATLAB 进程中的后续重复运行使用。

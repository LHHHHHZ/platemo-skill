# SET-NSGAIII 适配器

仅运行或分析 SET_NSGAIII 时读取本文件。id 为 set_nsgaiii，源码在 scripts/adapters/set_nsgaiii/，这些要求不适用于普通算法。

运行需要支持 pyenv 的 MATLAB R2019b+，算法目录 `.venv/Scripts/python.exe` 内需安装 NumPy、SciPy、PyTorch。适配器核对实际解释器及 SetTransformer.py 的导入位置。解析结果的 Python 可以不同；当前专属解释器发现规则面向 Windows。

参数 `[TRAIN,GW]` 按算法实现解释。TRAIN=0 必须加载权重、禁止在线训练；TRAIN=1 必须加载权重并微调，缺权重后从零训练属于降级；TRAIN=2 仅在用户明确要求纯在线模式时使用，必须真正训练。

记录实际模式、权重路径/hash、训练步数、预测成功/失败、注入和留存及 GA 回退。Python 返回成功还需 MATLAB 日志证明真实预测解注入。初始化/预测/转换失败或 GA 回退均阻止有效实验。预算过短未触发机制时为 not_exercised；检查 maxFE、实际 N、GW 和预测间隔，不为通过校验擅自切模式。留存数为 0 可以是有效运行，质量由指标判断。

设置 Python random、NumPy、PyTorch CPU/CUDA 随机流及严格确定性选项，关闭 cuDNN benchmark，提前配置 cuBLAS workspace。无确定性实现时失败；CUDA 已在不兼容设置下初始化则使用新 MATLAB 进程。结束恢复随机状态和临时接口，workspace 配置保留到进程结束。跨硬件/依赖版本不保证完全相同。

证据保存在逐次 diagnostics、清单和结果来源。解析侧再次检查权重来源、模式、计数器及随机性。历史结果缺证据时重跑，不能伪造诊断。

扩展测试见 test_adapter_runtime_validation.py、test_adapter_seed_validation.py、test_adapter_runtime_runner.m 和 test_adapter_seed_runner.m。真实外部随机流测试需要 PyTorch，MATLAB 验证需要平台和本算法。

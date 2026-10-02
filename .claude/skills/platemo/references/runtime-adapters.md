# 可选运行适配器

通用核心负责调度、来源、最终指标、MATLAB seed、配对比较和迭代规则。算法特有依赖、模式、模型权重、内部计数器及外部随机流由适配器处理。

## 选择与能力

scripts/adapters/registry.json 是 MATLAB 和 Python 共用的本地注册表，包含 id、version、algorithms、matlab_class、python_module、capabilities、sources、reference。只加载命中的算法扩展，按需阅读其 reference。

算法配置可选 adapter，默认 auto。未注册普通算法使用 none；已注册算法自动选择其适配器，不能用 none 绕过。显式 id 必须匹配算法注册关系，不从实验配置任意导入外部模块。

可声明 required_capabilities，例如 `["matlab_random","runtime_mechanism"]`。matlab_random 来自核心，其余能力必须由适配器提供；缺失在仿真前报错。普通算法无需虚构专属诊断。

记录的 runtime_adapter 保存 id、version、capabilities，sources 的 hash 纳入算法来源。比较时核对身份/版本和实际诊断。所需文件缺失、适配器不可用或失败时不能静默退回通用流程。旧清单没有身份记录时，仍按类名验证已有专属证据，不补造记录；新运行产生完整来源。

新 seed_policy 使用 schema_version=2，MATLAB 流和 external_policy=adapter-defined 分开描述。仍支持读取旧 v1 协议，但不同协议不能强行合并。运行器源码升级改变 hash 后，新旧批次可能需要重跑才能严格比较。

## 报告范围

validation.verification_scope 按运行报告 matlab_random、adapter、adapter_version、verified_capabilities、runtime_mechanism、external_random_sources。not_checked 表示未验证，不表示失败或通过。

普通算法可完成通用比较。研究若依赖未验证机制，应先补适配器或其他证据；已声明能力缺失会阻止严格比较和迭代。已验证某些随机库不代表所有外部随机源都受控。

## 扩展接口

实现放在 scripts/adapters/<id>/，在注册表登记算法类名和能力，并提供独立文档及 test_adapter_* 测试。sources 第一项为 MATLAB 类文件，列全其他执行源码，路径限制在 scripts 内。

MATLAB 构造接口为 `(params,scriptDir,logPath,seed)`，实现 ensurePreflight、attach(info,final)、report(final)、close。attach 返回补充诊断后的 info，不改变搜索逻辑；结束和异常时恢复临时接口及状态。

Python 模块提供 validate(record)，返回 issue 列表，空列表表示声明能力的证据通过。解析侧不初始化训练环境或强制导入运行侧重依赖，必要字段缺失或异常需明确失败。

出现新的实际适配需求后再抽取共用实现，不提前建立复杂插件框架。

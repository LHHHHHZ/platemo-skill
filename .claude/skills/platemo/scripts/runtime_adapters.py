# -*- coding: utf-8 -*-
"""从本地注册表选择适配器；普通算法不导入任何算法扩展。"""
import importlib
import json
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REGISTRY = SCRIPTS / 'adapters/registry.json'


def resolve_adapter(algorithm, requested='auto', required=()):
    registry = json.loads(REGISTRY.read_text(encoding='utf-8'))
    if registry.get('schema_version') != 1 or not isinstance(registry.get('adapters'), list):
        raise ValueError('Unsupported adapter registry')
    if not isinstance(requested, str) or not isinstance(required, (list, tuple)):
        raise ValueError('adapter must be a name; required_capabilities must be a list')
    matches = [entry for entry in registry['adapters'] if algorithm in entry['algorithms']]
    if len(matches) > 1:
        raise ValueError('Ambiguous algorithm adapter registration')
    entry = matches[0] if matches else {'id': 'none', 'version': 1, 'capabilities': [], 'sources': []}
    if requested not in ('auto', entry['id']):
        raise ValueError(f'Adapter {requested} is unavailable or incompatible with {algorithm}')
    if not set(required).issubset({'matlab_random', *entry['capabilities']}):
        raise ValueError('Required capabilities are not provided by the selected adapter')
    for source in entry['sources']:
        path = (SCRIPTS / source).resolve()
        if not path.is_relative_to(SCRIPTS) or not path.is_file():
            raise ValueError(f'Required adapter source is unavailable: {source}')
    return entry


def validate_record(record, spec=None):
    """返回实际校验证据及能力范围，声明了扩展时不能静默降级。"""
    from seed_runtime import randomness_issues
    issues = randomness_issues(record)
    scope = {'adapter': 'unresolved', 'matlab_random': not issues,
             'runtime_mechanism': 'not_checked', 'external_random_sources': 'not_checked',
             'verified_capabilities': []}
    try:
        spec = spec or {}
        entry = resolve_adapter(record['algorithm'], spec.get('adapter', 'auto'),
                                spec.get('required_capabilities', []))
        scope['adapter'] = entry['id']
        scope['adapter_version'] = entry['version']
        evidence = record.get('runtime_adapter')
        expected = {key: entry[key] for key in ('id', 'version', 'capabilities')}
        if evidence is not None and evidence != expected:
            raise ValueError('Recorded adapter identity/version/capabilities do not match registration')
        if 'adapter' in spec and evidence is None:
            raise ValueError('Configured adapter has no recorded identity')
        if entry['id'] != 'none':
            module = importlib.import_module(entry['python_module'])
            adapter_issues = module.validate(record)
            issues.extend(adapter_issues)
            if not adapter_issues:
                scope['verified_capabilities'] = entry['capabilities']
                if 'runtime_mechanism' in entry['capabilities']:
                    scope['runtime_mechanism'] = 'passed'
                scope['external_random_sources'] = 'see_verified_capabilities'
    except Exception as exc:  # 扩展异常必须转成失败证据，不能留下旧成功报告。
        issues.append({'code': 'adapter_validation_failed', 'message': str(exc)})
    return issues, scope

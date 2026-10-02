# -*- coding: utf-8 -*-
"""预先锁定本轮迭代标准，依据完整配对实验给出三态建议；不改写算法源码。"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import scipy
from scipy.stats import wilcoxon

from experiment_manifest import file_hash, load_manifest
from parse_results import collect, summarize, validate_evidence
from metric_directions import resolve_directions


def validate_policy(policy):
    required = {'schema_version', 'primary_metric', 'metrics', 'required_improved_fraction', 'min_runs', 'alpha'}
    if (not isinstance(policy, dict) or set(policy) != required
            or type(policy['schema_version']) is not int or policy['schema_version'] != 1):
        raise ValueError('Policy must contain exactly the documented schema_version=1 fields')
    if type(policy['min_runs']) is not int or policy['min_runs'] < 2:
        raise ValueError('Policy min_runs must be an integer >= 2')
    for key in ('alpha', 'required_improved_fraction'):
        value = policy[key]
        upper_inclusive = key == 'required_improved_fraction'
        if (type(value) not in (int, float) or not math.isfinite(value) or value <= 0
                or (value > 1 if upper_inclusive else value >= 1)):
            raise ValueError(f'Invalid policy {key}')
    metrics = policy['metrics']
    if not isinstance(metrics, dict) or not metrics or policy['primary_metric'] not in metrics:
        raise ValueError('primary_metric must be one of the protected metrics')
    for name, rule in metrics.items():
        fields = {'scale', 'max_regression'} | ({'min_improvement'} if name == policy['primary_metric'] else set())
        if not isinstance(rule, dict) or set(rule) - {'direction'} != fields or rule['scale'] not in ('relative', 'absolute'):
            raise ValueError(f'Invalid metric policy: {name}')
        resolve_directions([name], {name: rule['direction']} if 'direction' in rule else {})
        for field in fields - {'scale'}:
            value = rule[field]
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f'{name}.{field} must be finite and non-negative')
        if name == policy['primary_metric'] and rule['min_improvement'] <= 0:
            raise ValueError('Primary min_improvement must be positive')
    return policy


def checked_data(manifests, labels, policy, baseline=''):
    args = SimpleNamespace(manifest=None, experiment=[f'{name}={path}' for name, path in manifests],
        algorithms=','.join(labels), problems='', metrics=','.join(policy['metrics']), baseline=baseline,
        allow_legacy=False, data_dir=None, series=[], min_runs=policy['min_runs'], preview=False,
        metric_directions={name: rule['direction'] for name, rule in policy['metrics'].items() if 'direction' in rule})
    try:
        grouped = collect(args)
    except SystemExit as exc:
        raise ValueError(str(exc)) from exc
    with np.errstate(over='ignore', invalid='ignore'):
        rows = summarize(grouped, args.metric_directions)
    validation = validate_evidence(args, grouped, rows)
    return args, rows, validation


def cases_from_rows(rows):
    return [{'problem': problem, 'M': m, 'D': d} for problem, m, d in
            sorted({(row['problem'], row['M'], row['D']) for row in rows})]


def prepare_plan(baseline_path, label, policy, output):
    policy = validate_policy(policy)
    baseline_path, manifest = load_manifest(baseline_path)
    labels = {item.get('label', item['class']): item['class'] for item in manifest['config']['algorithms']}
    if label not in labels:
        raise ValueError('Choose an exact algorithm label from the baseline manifest')
    _, rows, validation = checked_data([('old', baseline_path)], [f'old/{label}'], policy)
    if validation['status'] != 'ready':
        raise ValueError('Baseline evidence is insufficient: ' + json.dumps(validation['issues']))
    plan = {'schema_version': 1, 'kind': 'iteration_plan', 'created_at': datetime.now(timezone.utc).isoformat(),
            'baseline_manifest': str(baseline_path), 'baseline_sha256': file_hash(baseline_path),
            'algorithm_label': label, 'algorithm_class': labels[label], 'policy': policy,
            'cases': cases_from_rows(rows), 'seeds': manifest['config']['seeds'],
            'decision_method': 'shifted_wilcoxon_holm_v1'}
    # 已预先登记的方案不能覆盖；新一轮使用新文件。
    with Path(output).open('x', encoding='utf-8') as stream:
        json.dump(plan, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    return plan


def shifted_pvalue(effects, threshold, alternative, rounding_error=0):
    shifted = np.asarray(effects, dtype=float) - threshold
    if not np.isfinite(shifted).all():
        raise ValueError('Non-finite effect after threshold shift')
    # 相减带来的机器舍入误差不能作为越过预设门槛的证据。
    shifted[np.abs(shifted) <= rounding_error] = 0
    if not np.any(shifted):
        return 1.0
    result = wilcoxon(shifted, alternative=alternative, zero_method='pratt', method='auto')
    p = float(result.pvalue)
    if not math.isfinite(p) or not 0 <= p <= 1:
        raise ValueError('Statistical test did not produce a finite p-value')
    return p


def holm_adjust(pvalues):
    """对本轮所有问题、指标和方向假设做同一个 Holm 校正。"""
    adjusted = [1.0] * len(pvalues)
    running = 0.0
    for rank, index in enumerate(sorted(range(len(pvalues)), key=lambda i: pvalues[i])):
        running = max(running, (len(pvalues) - rank) * pvalues[index])
        adjusted[index] = min(1.0, running)
    return adjusted


def assess_samples(samples, old_label, new_label, policy, cases):
    validate_policy(policy)
    if not cases:
        raise ValueError('The prepared test suite must not be empty')
    checks, hypotheses = [], []
    for case in cases:
        for metric, rule in policy['metrics'].items():
            prefix = (case['problem'], case['M'], case['D'])
            old = samples[(*prefix, old_label, metric)]
            new = samples[(*prefix, new_label, metric)]
            if set(old) != set(new) or len(old) < policy['min_runs']:
                raise ValueError('Paired seed coverage is incomplete')
            seeds = sorted(old)
            before = np.asarray([old[seed] for seed in seeds], dtype=float)
            after = np.asarray([new[seed] for seed in seeds], dtype=float)
            if rule['scale'] == 'relative' and np.any(before == 0):
                raise ValueError(f'{metric}: zero baseline makes relative effect undefined; predeclare absolute thresholds in a new plan')
            with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
                direction = resolve_directions([metric], {metric: rule['direction']} if 'direction' in rule else {})[metric]
                effects = (after - before) if direction == 'max' else (before - after)
                if rule['scale'] == 'relative':
                    effects = effects / np.abs(before)
                rounding_error = 8 * np.finfo(float).eps * np.maximum(np.abs(before), np.abs(after))
                if rule['scale'] == 'relative':
                    rounding_error = rounding_error / np.abs(before)
            if not np.isfinite(effects).all():
                raise ValueError('Non-finite paired effect')
            with np.errstate(over='ignore', invalid='ignore'):
                median_effect = float(np.median(effects))
            if not math.isfinite(median_effect):
                raise ValueError('Non-finite effect summary')
            check = {**case, 'metric': metric, 'scale': rule['scale'], 'paired_seeds': seeds,
                     'n': len(seeds), 'median_effect': median_effect,
                     'max_regression': rule['max_regression'], 'tests': {}}
            specs = [('within_tolerance', -rule['max_regression'], 'greater'),
                     ('excessive_regression', -rule['max_regression'], 'less')]
            if metric == policy['primary_metric']:
                check['min_improvement'] = rule['min_improvement']
                specs.append(('meaningful_improvement', rule['min_improvement'], 'greater'))
            for name, threshold, alternative in specs:
                test = {'threshold': threshold, 'alternative': alternative,
                        'p': shifted_pvalue(effects, threshold, alternative, rounding_error)}
                check['tests'][name] = test
                hypotheses.append(test)
            checks.append(check)
    for test, corrected in zip(hypotheses, holm_adjust([test['p'] for test in hypotheses])):
        test['p_holm'] = corrected
        test['supported'] = corrected < policy['alpha']
    for check in checks:
        median = check['median_effect']
        check['within_tolerance'] = median > -check['max_regression'] and check['tests']['within_tolerance']['supported']
        check['excessive_regression'] = median < -check['max_regression'] and check['tests']['excessive_regression']['supported']
        check['meaningful_improvement'] = (check['metric'] == policy['primary_metric']
            and median > check.get('min_improvement', math.inf)
            and check['tests'].get('meaningful_improvement', {}).get('supported', False))
    improved = sum(check['meaningful_improvement'] for check in checks)
    required = math.ceil(len(cases) * policy['required_improved_fraction'])
    if any(check['excessive_regression'] for check in checks):
        decision, reason = 'revert', 'Confirmed regression exceeds a predeclared tolerance.'
    elif improved >= required and all(check['within_tolerance'] for check in checks):
        decision, reason = 'keep', 'Required primary improvements and all regression safeguards are supported.'
    else:
        decision, reason = 'insufficient_evidence', 'Improvement or regression safeguards remain unproven; do not infer failure from non-significance.'
    return {'decision': decision, 'can_apply': decision != 'insufficient_evidence', 'reason': reason,
            'improved_cases': improved, 'required_improved_cases': required, 'total_cases': len(cases),
            'checks': checks, 'hypothesis_count': len(hypotheses), 'multiplicity_correction': 'holm'}


def evaluate_plan(plan_path, candidate_path, candidate_label=None):
    plan_path, candidate_path = Path(plan_path).resolve(), Path(candidate_path).resolve()
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    if (not isinstance(plan, dict) or plan.get('schema_version') != 1 or plan.get('kind') != 'iteration_plan'
            or plan.get('decision_method') != 'shifted_wilcoxon_holm_v1'):
        raise ValueError('Unsupported iteration plan')
    policy = validate_policy(plan['policy'])
    baseline_path = Path(plan['baseline_manifest'])
    if file_hash(baseline_path) != plan['baseline_sha256']:
        raise ValueError('Baseline manifest changed after plan preparation')
    _, candidate = load_manifest(candidate_path)
    binding = candidate['config'].get('iteration_plan', {})
    snapshot = candidate_path.parent / 'iteration_plan.json'
    if (not isinstance(binding, dict) or binding.get('sha256') != file_hash(plan_path)
            or not snapshot.is_file() or file_hash(snapshot) != file_hash(plan_path)):
        raise ValueError('Candidate did not lock this plan before execution, or the plan was changed afterward')
    label = candidate_label or plan['algorithm_label']
    labels = {item.get('label', item['class']): item['class'] for item in candidate['config']['algorithms']}
    if labels.get(label) != plan['algorithm_class']:
        raise ValueError('Candidate must identify the same algorithm class as the prepared baseline')
    old_label, new_label = f"old/{plan['algorithm_label']}", f'new/{label}'
    args, rows, validation = checked_data([('old', baseline_path), ('new', candidate_path)],
                                         [old_label, new_label], policy, old_label)
    common = {'schema_version': 1, 'plan': str(plan_path), 'plan_sha256': file_hash(plan_path), 'policy': policy,
              'baseline_manifest': str(baseline_path), 'candidate_manifest': str(candidate_path),
              'scipy_version': scipy.__version__, 'validation': validation}
    if not validation['can_iterate']:
        return {**common, 'decision': 'insufficient_evidence', 'can_apply': False,
                'reason': 'Experiment evidence failed strict validation.', 'checks': []}
    if cases_from_rows(rows) != plan['cases'] or candidate['config']['seeds'] != plan['seeds']:
        raise ValueError('Candidate must preserve the entire prepared test suite and seed list')
    return {**common, **assess_samples(args.seed_samples, old_label, new_label, policy, plan['cases'])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('--baseline', type=Path, required=True)
    prepare.add_argument('--algorithm', required=True, help='Exact baseline algorithm label')
    prepare.add_argument('--policy', type=Path, required=True)
    prepare.add_argument('--out', type=Path, required=True)
    evaluate = commands.add_parser('evaluate')
    evaluate.add_argument('--plan', type=Path, required=True)
    evaluate.add_argument('--candidate', type=Path, required=True)
    evaluate.add_argument('--candidate-label')
    evaluate.add_argument('--json', type=Path, required=True, dest='output')
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            policy = json.loads(args.policy.read_text(encoding='utf-8'))
            prepare_plan(args.baseline, args.algorithm, policy, args.out)
            print(f'ITERATION_PLAN={args.out.resolve()}')
            return 0
        report = evaluate_plan(args.plan, args.candidate, args.candidate_label)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if args.command == 'prepare':
            print(f'PLAN_REJECTED: {exc}', file=sys.stderr)
            return 2
        report = {'schema_version': 1, 'decision': 'insufficient_evidence', 'can_apply': False,
                  'reason': str(exc), 'checks': [], 'issues': [{'code': 'iteration_validation_failed', 'message': str(exc)}]}
    temporary = args.output.with_name(args.output.name + '.tmp')
    temporary.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(args.output)
    print(f"ITERATION_DECISION={report['decision']} CAN_APPLY={str(report['can_apply']).lower()}")
    print(report['reason'])
    return 0 if report['can_apply'] else 2


if __name__ == '__main__':
    sys.exit(main())

# -*- coding: utf-8 -*-
"""验证预登记、完整测试集保护、实际改善门槛和三态迭代决策。"""
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from scipy.io import savemat
import test_experiment_isolation as fixtures
import decide_iteration as decision


def policy(runs=10):
    return {'schema_version': 1, 'primary_metric': 'IGD',
            'metrics': {'IGD': {'scale': 'relative', 'min_improvement': .01, 'max_regression': .01},
                        'HV': {'scale': 'relative', 'max_regression': .01}},
            'required_improved_fraction': .5, 'min_runs': runs, 'alpha': .05}


class DecisionRuleTests(unittest.TestCase):
    def assess(self, igd=.1, hv=0., runs=10, second=None, rule=None):
        cases = [{'problem': 'P1', 'M': 3, 'D': 20}]
        effects = [(igd, hv)]
        if second is not None:
            cases.append({'problem': 'P2', 'M': 3, 'D': 20})
            effects.append(second)
        samples = {}
        for case, pair in zip(cases, effects):
            for metric, effect in zip(('IGD', 'HV'), pair):
                prefix = (case['problem'], 3, 20)
                samples[(*prefix, 'old', metric)] = {i: 1. for i in range(runs)}
                values = np.broadcast_to(effect, (runs,))
                samples[(*prefix, 'new', metric)] = {i: 1 + value * (-1 if metric == 'IGD' else 1)
                                                       for i, value in enumerate(values)}
        return decision.assess_samples(samples, 'old', 'new', rule or policy(runs), cases)

    def test_keep_requires_meaningful_gain_and_all_safeguards(self):
        result = self.assess(hv=-.005)
        self.assertEqual(result['decision'], 'keep')
        self.assertTrue(result['can_apply'])
        self.assertEqual(result['hypothesis_count'], 5)
        self.assertTrue(all(check['within_tolerance'] for check in result['checks']))

    def test_confirmed_hv_regression_overrides_igd_gain(self):
        self.assertEqual(self.assess(hv=-.1)['decision'], 'revert')

    def test_small_gain_equal_results_and_small_samples_are_inconclusive(self):
        for args in ({'igd': .005}, {'igd': 0}, {'runs': 3}, {'igd': .01}, {'hv': -.01}):
            with self.subTest(args=args):
                result = self.assess(**args)
                self.assertEqual(result['decision'], 'insufficient_evidence')
                self.assertFalse(result['can_apply'])

    def test_full_suite_protects_previously_good_problem(self):
        self.assertEqual(self.assess(second=(-.1, 0))['decision'], 'revert')
        result = self.assess(second=(0, 0))
        self.assertEqual(result['decision'], 'keep')
        self.assertEqual(result['required_improved_cases'], 1)
        rule = policy()
        rule['required_improved_fraction'] = 1
        self.assertEqual(self.assess(second=(0, 0), rule=rule)['decision'], 'insufficient_evidence')

    def test_non_significant_regression_is_not_proof_of_safety(self):
        result = self.assess(hv=[-.02, 0] * 5)
        self.assertEqual(result['decision'], 'insufficient_evidence')

    def test_invalid_policies_are_rejected(self):
        invalid = [None, {}, {**policy(), 'unexpected': 1}, {**policy(), 'schema_version': True},
                   {**policy(), 'alpha': 1}, {**policy(), 'alpha': float('nan')},
                   {**policy(), 'min_runs': True}, {**policy(), 'min_runs': 1},
                   {**policy(), 'required_improved_fraction': 0}, {**policy(), 'primary_metric': 'GD'}]
        for metric, field, value in [('IGD', 'min_improvement', 0), ('HV', 'scale', 'percent'),
                                     ('HV', 'max_regression', -1), ('HV', 'max_regression', True)]:
            rule = policy()
            rule['metrics'][metric][field] = value
            invalid.append(rule)
        rule = policy()
        rule['metrics']['unknown'] = {'scale': 'relative', 'max_regression': .01}
        invalid.append(rule)
        for rule in invalid:
            with self.subTest(rule=rule), self.assertRaises(ValueError):
                decision.validate_policy(rule)

    def test_holm_and_shifted_tests_handle_boundaries(self):
        np.testing.assert_allclose(decision.holm_adjust([.01, .04, .03]), [.03, .06, .06])
        self.assertEqual(decision.shifted_pvalue([.01] * 3, .01, 'greater'), 1)
        with self.assertRaises(ValueError): decision.shifted_pvalue([float('inf')], 0, 'greater')
        with patch.object(decision, 'wilcoxon', return_value=SimpleNamespace(pvalue=float('nan'))):
            with self.assertRaises(ValueError): decision.shifted_pvalue([1, 2], 0, 'greater')

    def test_incomplete_pairs_zero_baseline_and_overflow_fail_closed(self):
        case = [{'problem': 'P', 'M': 2, 'D': 3}]
        rule = policy(2)
        rule['metrics'].pop('HV')
        samples = {('P', 2, 3, 'old', 'IGD'): {1: 0., 2: 0.},
                   ('P', 2, 3, 'new', 'IGD'): {1: -1., 2: -1.}}
        with self.assertRaisesRegex(ValueError, 'zero baseline'):
            decision.assess_samples(samples, 'old', 'new', rule, case)
        rule['metrics']['IGD']['scale'] = 'absolute'
        self.assertEqual(decision.assess_samples(samples, 'old', 'new', rule, case)['decision'], 'insufficient_evidence')
        samples[('P', 2, 3, 'new', 'IGD')].pop(2)
        with self.assertRaisesRegex(ValueError, 'coverage'):
            decision.assess_samples(samples, 'old', 'new', rule, case)
        samples[('P', 2, 3, 'new', 'IGD')] = {1: -1.7e308, 2: -1.7e308}
        with self.assertRaisesRegex(ValueError, 'summary'):
            decision.assess_samples(samples, 'old', 'new', rule, case)
        with self.assertRaisesRegex(ValueError, 'empty'):
            decision.assess_samples({}, 'old', 'new', rule, [])


class DecisionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExperimentIsolationTests(methodName='runTest')
        self.fixture.setUp()
        self.root = self.fixture.root
        self.old, _ = self.fixture.make_experiment('old', runs=10, algorithms=[{'class': 'NSGAII'}])
        self.plan = self.root / 'plan.json'
        decision.prepare_plan(self.old, 'NSGAII', policy(), self.plan)

    def tearDown(self):
        self.fixture.tearDown()

    def candidate(self, name='new', igd_factor=.9, hv=.5, bind=True):
        path, data = self.fixture.make_experiment(name, runs=10, algorithms=[{'class': 'NSGAII'}])
        for record in data['records']:
            result = path.parent / record['file']
            savemat(result, {'metric': {'IGD': record['run'] * igd_factor, 'HV': hv}})
            record['sha256'] = fixtures.file_hash(result)
        if bind:
            data['config']['iteration_plan'] = {'path': str(self.plan), 'sha256': fixtures.file_hash(self.plan)}
            (path.parent / 'iteration_plan.json').write_bytes(self.plan.read_bytes())
        self.fixture.rewrite(path, data)
        return path, data

    def test_end_to_end_keep_and_revert(self):
        path, _ = self.candidate()
        self.assertEqual(decision.evaluate_plan(self.plan, path)['decision'], 'keep')
        path, _ = self.candidate('worse', hv=.4)
        self.assertEqual(decision.evaluate_plan(self.plan, path)['decision'], 'revert')

    def test_plan_baseline_and_snapshot_tampering_are_rejected(self):
        path, _ = self.candidate()
        original = self.plan.read_bytes()
        self.plan.write_bytes(original + b' ')
        with self.assertRaisesRegex(ValueError, 'lock'): decision.evaluate_plan(self.plan, path)
        self.plan.write_bytes(original)
        (path.parent / 'iteration_plan.json').write_bytes(original + b' ')
        with self.assertRaisesRegex(ValueError, 'lock'): decision.evaluate_plan(self.plan, path)
        (path.parent / 'iteration_plan.json').write_bytes(original)
        self.old.write_bytes(self.old.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'Baseline manifest changed'): decision.evaluate_plan(self.plan, path)

    def test_unbound_candidate_and_wrong_algorithm_are_rejected(self):
        path, _ = self.candidate(bind=False)
        with self.assertRaisesRegex(ValueError, 'lock'): decision.evaluate_plan(self.plan, path)
        path, _ = self.candidate('bound')
        with self.assertRaisesRegex(ValueError, 'same algorithm'): decision.evaluate_plan(self.plan, path, 'NSGAIII')

    def test_missing_metric_and_seed_mismatch_are_insufficient(self):
        path, data = self.candidate()
        result = path.parent / data['records'][0]['file']
        savemat(result, {'metric': {'IGD': .9}})
        data['records'][0]['sha256'] = fixtures.file_hash(result)
        self.fixture.rewrite(path, data)
        report = decision.evaluate_plan(self.plan, path)
        self.assertEqual(report['decision'], 'insufficient_evidence')
        self.assertFalse(report['can_apply'])
        path, data = self.candidate('seed')
        data['config']['seeds'][0] = 100
        data['records'][0]['seed'] = 100
        data['records'][0]['randomness'] = fixtures.randomness(100, 'NSGAII')
        self.fixture.rewrite(path, data)
        self.assertEqual(decision.evaluate_plan(self.plan, path)['decision'], 'insufficient_evidence')

    def test_prepare_rejects_bad_label_insufficient_runs_and_existing_plan(self):
        for label, rule, error in [('bad', policy(), ValueError), ('NSGAII', policy(20), ValueError),
                                   ('NSGAII', policy(), FileExistsError)]:
            with self.assertRaises(error): decision.prepare_plan(self.old, label, rule, self.plan)

    def test_omitting_a_prepared_problem_cannot_enable_keep(self):
        data = json.loads(self.old.read_text())
        data['config']['problems'].append({'class': 'LSMOP2', 'M': 3, 'D': 500, 'params': []})
        extra = copy.deepcopy(data['records'])
        for record in extra:
            source = self.old.parent / record['file']
            target = source.with_name(source.name.replace('LSMOP1', 'LSMOP2'))
            target.write_bytes(source.read_bytes())
            record.update(problem='LSMOP2', problem_index=2, file=target.relative_to(self.old.parent).as_posix())
        data['records'].extend(extra)
        data['expected_runs'] = len(data['records'])
        self.fixture.rewrite(self.old, data)
        self.plan = self.root / 'complete_plan.json'
        plan = decision.prepare_plan(self.old, 'NSGAII', policy(), self.plan)
        self.assertEqual(len(plan['cases']), 2)
        path, _ = self.candidate()
        output = self.root / 'omitted_problem.json'
        self.assertEqual(decision.main(['evaluate', '--plan', str(self.plan), '--candidate', str(path),
                                        '--json', str(output)]), 2)
        self.assertFalse(json.loads(output.read_text())['can_apply'])

    def test_seed_order_must_match_prepared_list(self):
        path, data = self.candidate()
        data['config']['seeds'].reverse()
        for record, seed in zip(data['records'], data['config']['seeds']):
            record['seed'] = seed
            record['randomness'] = fixtures.randomness(seed, 'NSGAII')
        self.fixture.rewrite(path, data)
        with self.assertRaisesRegex(ValueError, 'entire prepared'):
            decision.evaluate_plan(self.plan, path)

    def test_candidate_label_can_change_but_algorithm_class_cannot(self):
        path, data = self.candidate()
        data['config']['algorithms'][0]['label'] = 'candidate'
        for record in data['records']: record['label'] = 'candidate'
        self.fixture.rewrite(path, data)
        self.assertEqual(decision.evaluate_plan(self.plan, path, 'candidate')['decision'], 'keep')

    def test_collection_errors_are_converted_to_validation_errors(self):
        with patch.object(decision, 'collect', side_effect=SystemExit('bad protocol')):
            with self.assertRaisesRegex(ValueError, 'bad protocol'):
                decision.checked_data([], [], policy())

    def test_cli_writes_fresh_failure_and_success_reports(self):
        path, _ = self.candidate()
        output = self.root / 'decision.json'
        args = ['evaluate', '--plan', str(self.plan), '--candidate', str(path), '--json', str(output)]
        self.assertEqual(decision.main(args), 0)
        self.assertEqual(json.loads(output.read_text())['decision'], 'keep')
        self.plan.write_text('[]', encoding='utf-8')
        self.assertEqual(decision.main(args), 2)
        self.assertFalse(json.loads(output.read_text())['can_apply'])
        rule = self.root / 'policy.json'
        rule.write_text(json.dumps(policy()), encoding='utf-8')
        args = ['prepare', '--baseline', str(self.old), '--algorithm', 'NSGAII', '--policy', str(rule),
                '--out', str(self.root / 'second_plan.json')]
        self.assertEqual(decision.main(args), 0)
        self.assertEqual(decision.main(args), 2)


if __name__ == '__main__': unittest.main()

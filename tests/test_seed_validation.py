# -*- coding: utf-8 -*-
"""验证随机性证据、真实 Python 随机流和按 seed 配对的统计检验。"""
import copy
import json
import os
import random
import unittest
from unittest.mock import patch

import numpy as np
from scipy.stats import wilcoxon
import test_experiment_isolation as fixtures
from seed_runtime import RandomStateGuard, randomness_issues


class SeedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExperimentIsolationTests(methodName="runTest")
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_invalid_seed_plans_and_record_seed_mismatch_are_rejected(self):
        for name, seeds in [('duplicate',[1,1,2]),('short',[1]),('negative',[-1,2,3]),
                            ('float',[1.5,2,3]),('bool',[True,2,3]),('large',[2**32,2,3]),('record',[0,1,2])]:
            path, data = self.fixture.make_experiment(name)
            data['config']['seeds'] = seeds
            if name == 'record': data['records'][0]['seed'] = 100
            self.fixture.rewrite(path,data)
            with self.assertRaisesRegex(ValueError,'seed'):
                fixtures.load_manifest(path)

    def test_missing_or_incomplete_randomness_cannot_enable_iteration(self):
        for kind in ('missing','matlab_late','python_missing','python_seed','cuda_unseeded','nondeterministic'):
            path, data = self.fixture.make_experiment(kind, algorithms=[{'class':'SET_NSGAIII','params':[]},{'class':'NSGAIII','params':[]}])
            record = data['records'][0]
            if kind == 'missing': del record['randomness']
            elif kind == 'matlab_late': record['randomness']['matlab']['initialized_before_problem'] = False
            elif kind == 'python_missing': del record['randomness']['python']
            elif kind == 'python_seed': record['randomness']['python']['seed'] = 999
            elif kind == 'cuda_unseeded': record['runtime_diagnostics']['models'][0]['device'] = 'cuda'
            elif kind == 'nondeterministic': record['randomness']['python']['deterministic_algorithms'] = False
            self.fixture.rewrite(path,data)
            out = path.parent/'metrics.json'
            result = self.fixture.cli('--manifest',path,'--baseline','NSGAIII','--json',out)
            payload=json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(result.returncode,2)
            self.assertFalse(payload['can_iterate'])
            self.assertEqual(payload['tests'],[])
            self.assertIn('randomness_unverified',{issue['code'] for issue in payload['validation']['issues']})

    def test_different_seed_sets_block_paired_comparison(self):
        first,_=self.fixture.make_experiment('first')
        second,_=self.fixture.make_experiment('second',seeds=[10,20,30])
        out=self.fixture.root/'metrics.json'
        result=self.fixture.cli('--experiment',f'a={first}','--experiment',f'b={second}','--baseline','a/SET_NSGAIII','--json',out)
        payload=json.loads(out.read_text(encoding='utf-8'))
        self.assertEqual(result.returncode,2)
        self.assertIn('paired_seeds_mismatch',{issue['code'] for issue in payload['validation']['issues']})

    def test_old_manifests_without_seeds_cannot_be_used_for_iteration(self):
        path,data=self.fixture.make_experiment('old')
        del data['config']['seeds']
        del data['config']['seed_policy']
        for record in data['records']:
            del record['seed']
            del record['randomness']
        self.fixture.rewrite(path,data)
        result=self.fixture.cli('--manifest',path)
        self.assertEqual(result.returncode,2)
        self.assertIn('randomness_unverified',result.stderr)

    def test_pairing_uses_seed_not_record_order(self):
        rows=[{'problem':'p','M':2,'D':5,'metric':'IGD','algorithm':'base','values':[30,20,10]},
              {'problem':'p','M':2,'D':5,'metric':'IGD','algorithm':'new','values':[11,22,33]}]
        samples={('p',2,5,'base','IGD'):{3:30,2:20,1:10},
                 ('p',2,5,'new','IGD'):{1:11,2:22,3:33}}
        result=fixtures.parser.rank_tests(rows,'base',.05,samples)[0]
        expected=float(wilcoxon([1,2,3],zero_method='pratt',method='auto').pvalue)
        self.assertEqual(result['p'],expected)
        self.assertEqual(result['paired_seeds'],[1,2,3])
        self.assertEqual(result['method'],'wilcoxon_signed_rank')
        self.assertEqual(fixtures.parser.compare_samples([1,2,3],[1,2,3],False,.05,paired=True),('=',1.0))
        with self.assertRaises(ValueError):
            fixtures.parser.compare_samples([1,2],[1,2,3],False,.05,paired=True)
        # 大的区组偏移抵消后，配对差异方向必须按差值判断。
        symbol,p=fixtures.parser.compare_samples(np.arange(10)*100+1,np.arange(10)*100,False,.05,paired=True)
        self.assertEqual(symbol,'-')
        self.assertLess(p,.05)
        symbol,p=fixtures.parser.compare_samples([1]*10+[0]*30,[0]*40,True,.05,paired=True)
        self.assertEqual(symbol,'+')
        self.assertLess(p,.05)

    def test_valid_comparison_reports_paired_method(self):
        path,_=self.fixture.make_experiment('valid',algorithms=[{'class':'NSGAII','params':[]},{'class':'NSGAIII','params':[]}])
        out=path.parent/'metrics.json'
        result=self.fixture.cli('--manifest',path,'--baseline','NSGAIII','--json',out)
        payload=json.loads(out.read_text(encoding='utf-8'))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(payload['can_iterate'])
        self.assertTrue(all(item['method']=='wilcoxon_signed_rank' for item in payload['tests']))

    def test_randomness_validator_accepts_cuda_and_single_model_and_rejects_malformed_evidence(self):
        record={'algorithm':'SET_NSGAIII','seed':11,'randomness':fixtures.randomness(11,'SET_NSGAIII'),
                'runtime_diagnostics':fixtures.passed_diagnostics()}
        record['runtime_diagnostics']['models']=record['runtime_diagnostics']['models'][0]
        record['runtime_diagnostics']['models']['device']='cuda'
        record['randomness']['python']['torch_cuda']=True
        self.assertEqual(randomness_issues(record),[])
        self.assertEqual(randomness_issues({'algorithm':'NSGAIII','seed':11,'randomness':fixtures.randomness(11,'NSGAIII')}),[])
        for invalid in ({}, {'algorithm':'SET_NSGAIII','seed':True},
                        {**record,'randomness':None}, {**record,'runtime_diagnostics':{'models':['malformed']}}):
            self.assertEqual(randomness_issues(invalid)[0]['code'],'randomness_unverified')


class PythonRandomStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import torch
        except ImportError:
            raise unittest.SkipTest('PyTorch is only required for SET random-state tests')
        cls.torch=torch

    def test_seed_repeats_python_numpy_and_torch_and_restores_states(self):
        torch=self.torch
        random.seed(888)
        np.random.seed(888)
        torch.manual_seed(888)
        original_python=random.getstate()
        original_numpy=copy.deepcopy(np.random.get_state())
        original_cpu=torch.get_rng_state().clone()
        samples=[]
        for seed in (17,17,18):
            guard=RandomStateGuard(torch,seed)
            samples.append((random.random(),np.random.rand(),torch.rand(4).tolist()))
            info=json.loads(guard.info_json())
            self.assertEqual(info['seed'],seed)
            self.assertTrue(info['deterministic_algorithms'])
            guard.close()
            guard.close()
        self.assertEqual(samples[0],samples[1])
        self.assertNotEqual(samples[0],samples[2])
        self.assertEqual(original_python,random.getstate())
        self.assertTrue(np.array_equal(original_numpy[1],np.random.get_state()[1]))
        self.assertTrue(torch.equal(original_cpu,torch.get_rng_state()))

    def test_bad_seed_and_unsafe_existing_cuda_session_are_rejected(self):
        for seed in (-1,True,1.5,2**32):
            with self.assertRaises(ValueError): RandomStateGuard(self.torch,seed)
        with patch.dict(os.environ,{},clear=True),patch.object(self.torch.cuda,'is_initialized',return_value=True):
            with self.assertRaisesRegex(RuntimeError,'fresh MATLAB'): RandomStateGuard(self.torch,1)

    def test_partial_seed_initialization_failure_restores_random_states(self):
        torch=self.torch
        python_before=random.getstate()
        numpy_before=copy.deepcopy(np.random.get_state())
        cpu_before=torch.get_rng_state().clone()
        deterministic_before=torch.are_deterministic_algorithms_enabled()
        with patch.object(torch,'manual_seed',side_effect=RuntimeError('seed backend failed')):
            with self.assertRaisesRegex(RuntimeError,'seed backend failed'):
                RandomStateGuard(torch,17)
        self.assertEqual(python_before,random.getstate())
        self.assertTrue(np.array_equal(numpy_before[1],np.random.get_state()[1]))
        self.assertTrue(torch.equal(cpu_before,torch.get_rng_state()))
        self.assertEqual(deterministic_before,torch.are_deterministic_algorithms_enabled())


if __name__=='__main__': unittest.main()

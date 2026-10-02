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
from seed_runtime import randomness_issues as matlab_issues
from adapters.set_nsgaiii.random_state import RandomStateGuard
from adapters.set_nsgaiii.runtime import external_randomness_issues
from set_nsgaiii_fixtures import passed_diagnostics

def randomness_issues(record):
    issues = matlab_issues(record)
    if record.get('algorithm') == 'SET_NSGAIII':
        issues += external_randomness_issues(record)
    return issues


class AdapterSeedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExperimentIsolationTests(methodName='runTest')
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

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


    def test_randomness_validator_accepts_cuda_and_single_model_and_rejects_malformed_evidence(self):
        record={'algorithm':'SET_NSGAIII','seed':11,'randomness':fixtures.randomness(11,'SET_NSGAIII'),
                'runtime_diagnostics':passed_diagnostics()}
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

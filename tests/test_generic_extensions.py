# -*- coding: utf-8 -*-
"""通用流程不依赖算法扩展；方向、能力与扩展异常均明确校验。"""
import json
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

from scipy.io import savemat
import test_experiment_isolation as fixtures
import runtime_adapters
from metric_directions import parse_directions, resolve_directions
import decide_iteration


class GenericExtensionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExperimentIsolationTests(methodName='runTest')
        self.fixture.setUp()
        self.root = self.fixture.root

    def tearDown(self):
        self.fixture.tearDown()

    def test_comparison_without_optional_modules_or_torch(self):
        path, _ = self.fixture.make_experiment('plain', algorithms=[{'class':'NSGAII'}, {'class':'NSGAIII'}])
        scripts = self.root / 'core'
        scripts.mkdir()
        for source in fixtures.SCRIPTS.glob('*.py'):
            shutil.copy2(source, scripts/source.name)
        (scripts/'adapters').mkdir()
        shutil.copy2(fixtures.SCRIPTS/'adapters/registry.json', scripts/'adapters/registry.json')
        output = self.root/'plain.json'
        code = '''import sys, runpy, importlib.abc
class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'torch' or fullname.startswith(('torch.', 'adapters.')):
            raise AssertionError('Optional algorithm dependency imported: ' + fullname)
sys.meta_path.insert(0, BlockOptional())
runpy.run_path(sys.argv[0], run_name='__main__')
'''
        result = subprocess.run([sys.executable, '-c', 'import sys; sys.path.insert(0,sys.argv[1]); sys.argv=sys.argv[2:];\n'+code,
                                 str(scripts), str(scripts/'parse_results.py'), '--manifest', str(path),
                                 '--baseline','NSGAIII','--json',str(output)], capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(output.read_text())
        self.assertTrue(report['can_iterate'])
        for scope in report['validation']['verification_scope']:
            self.assertTrue(scope['matlab_random'])
            self.assertEqual(scope['adapter'],'none')
            self.assertEqual(scope['runtime_mechanism'],'not_checked')
            self.assertEqual(scope['verified_capabilities'],[])

    def test_unavailable_incompatible_and_required_capabilities_fail(self):
        for requested,required in [('unknown',[]),('set_nsgaiii',[]),('none',['runtime_mechanism'])]:
            with self.assertRaises(ValueError):
                runtime_adapters.resolve_adapter('NSGAII', requested, required)
        self.assertEqual(runtime_adapters.resolve_adapter('NSGAII','none',['matlab_random'])['id'],'none')

    def test_declared_capability_failure_blocks_comparison(self):
        path,data=self.fixture.make_experiment('required')
        data['config']['algorithms'][0]['required_capabilities']=['runtime_mechanism']
        self.fixture.rewrite(path,data)
        output=self.root/'report.json'
        result=self.fixture.cli('--manifest',path,'--json',output)
        self.assertEqual(result.returncode,2)
        report=json.loads(output.read_text())
        self.assertIn('adapter_validation_failed',{x['code'] for x in report['validation']['issues']})

    def test_recorded_identity_is_required_and_checked(self):
        path,data=self.fixture.make_experiment('metadata')
        spec=data['config']['algorithms'][0]
        spec['adapter']='none'
        record=data['records'][0]
        issues,_=runtime_adapters.validate_record(record,spec)
        self.assertEqual(issues[0]['code'],'adapter_validation_failed')
        record['runtime_adapter']={'id':'none','version':1,'capabilities':[]}
        self.assertEqual(runtime_adapters.validate_record(record,spec)[0],[])
        record['runtime_adapter']['version']=999
        self.assertEqual(runtime_adapters.validate_record(record,spec)[0][0]['code'],'adapter_validation_failed')

    def test_matlab_randomness_failure_is_not_claimed_verified(self):
        _,data=self.fixture.make_experiment('matlab')
        record=data['records'][0]
        record['randomness']['matlab']['initialized_before_problem']=False
        issues,scope=runtime_adapters.validate_record(record)
        self.assertEqual(issues[0]['code'],'randomness_unverified')
        self.assertFalse(scope['matlab_random'])

    def test_new_and_legacy_seed_protocols_are_distinguished(self):
        path,data=self.fixture.make_experiment('protocol')
        self.assertEqual(fixtures.load_manifest(path)[1]['config']['seed_policy']['schema_version'],2)
        data['config']['seed_policy']['external_policy']='all_verified'
        self.fixture.rewrite(path,data)
        with self.assertRaisesRegex(ValueError,'seed_policy'): fixtures.load_manifest(path)
        data['config']['seed_policy']={'schema_version':1,'design':'paired','matlab_generator':'twister',
                                      'entrypoint':'direct_solve','python_policy':'deterministic-v1'}
        self.fixture.rewrite(path,data)
        self.assertEqual(fixtures.load_manifest(path)[1]['config']['seed_policy']['schema_version'],1)

    def custom_experiment(self,name,direction=None,factor=1):
        path,data=self.fixture.make_experiment(name,runs=10,metrics=['CustomScore'])
        if direction is not None: data['config']['metric_directions']={'CustomScore':direction}
        for record in data['records']:
            file=path.parent/record['file']
            savemat(file,{'metric':{'CustomScore':float(record['run'])*factor}})
            record['sha256']=fixtures.file_hash(file)
        self.fixture.rewrite(path,data)
        return path,data

    def test_unknown_metric_requires_direction_and_does_not_poison_next_call(self):
        path,_=self.custom_experiment('unknown')
        output=self.root/'metrics.json'
        denied=self.fixture.cli('--manifest',path,'--metrics','CustomScore','--json',output)
        self.assertEqual(denied.returncode,2)
        self.assertFalse(json.loads(output.read_text())['can_iterate'])
        allowed=self.fixture.cli('--manifest',path,'--metrics','CustomScore','--metric-directions','CustomScore=max','--json',output)
        self.assertEqual(allowed.returncode,0,allowed.stderr)
        report=json.loads(output.read_text())
        self.assertEqual(report['rows'][0]['best'],10)
        self.assertEqual(report['metric_directions'],{'CustomScore':'max'})
        with self.assertRaises(ValueError): fixtures.parser.higher_better('CustomScore')

    def test_conflicting_experiment_and_cli_directions_are_rejected(self):
        path,_=self.custom_experiment('max','max')
        other,_=self.custom_experiment('min','min')
        for args in [('--manifest',path,'--metric-directions','CustomScore=min'),
                     ('--experiment',f'a={path}','--experiment',f'b={other}')]:
            result=self.fixture.cli(*args,'--metrics','CustomScore')
            self.assertEqual(result.returncode,2)
            self.assertIn('Conflicting',result.stderr)

    def test_custom_direction_is_locked_in_iteration_policy(self):
        old,_=self.custom_experiment('old','max')
        new,data=self.custom_experiment('new','max',factor=1.1)
        policy={'schema_version':1,'primary_metric':'CustomScore',
                'metrics':{'CustomScore':{'scale':'relative','direction':'max','min_improvement':.01,'max_regression':.01}},
                'min_runs':10,'required_improved_fraction':1,'alpha':.05}
        plan=self.root/'plan.json'
        decide_iteration.prepare_plan(old,'NSGAII',policy,plan)
        data['config']['iteration_plan']={'path':str(plan),'sha256':fixtures.file_hash(plan)}
        (new.parent/'iteration_plan.json').write_bytes(plan.read_bytes())
        self.fixture.rewrite(new,data)
        report=decide_iteration.evaluate_plan(plan,new)
        self.assertEqual(report['decision'],'keep')
        policy['metrics']['CustomScore']['direction']='min'
        with self.assertRaisesRegex(ValueError,'Conflicting'):
            decide_iteration.prepare_plan(old,'NSGAII',policy,self.root/'wrong_plan.json')

    def test_direction_validation_rejects_ambiguity(self):
        for raw in ['A=min,A=max','A=up','A','IGD=max','=min']:
            with self.subTest(raw=raw),self.assertRaises(ValueError): parse_directions(raw)
        for declared in ([],{'IGD':'max'},{'HV':'min'},{'x':'up'}):
            with self.assertRaises(ValueError): resolve_directions(['IGD'],declared)
        self.assertEqual(parse_directions('Score=max,Cost=min'),{'Score':'max','Cost':'min'})

    def test_public_docs_and_core_do_not_contain_specific_algorithm(self):
        repo=fixtures.SCRIPTS.parents[3]
        for path in [repo/'README.md',fixtures.SCRIPTS.parent/'SKILL.md',
                     fixtures.SCRIPTS/'run_platemo_batch.m',fixtures.SCRIPTS/'parse_results.py',fixtures.SCRIPTS/'seed_runtime.py']:
            text=path.read_text(encoding='utf-8')
            self.assertNotIn('SET_NSGAIII',text)
            self.assertNotIn('SET-NSGAIII',text)


if __name__=='__main__': unittest.main()

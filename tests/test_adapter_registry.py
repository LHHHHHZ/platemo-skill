"""注册适配器的身份、失败和混合算法校验。"""
import unittest
from unittest.mock import patch
import test_experiment_isolation as fixtures
import runtime_adapters

class AdapterRegistryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ExperimentIsolationTests(methodName='runTest')
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_registered_adapter_cannot_be_disabled_or_ignored(self):
        with self.assertRaises(ValueError): runtime_adapters.resolve_adapter('SET_NSGAIII','none')
        with patch.object(runtime_adapters,'SCRIPTS',self.fixture.root):
            with self.assertRaisesRegex(ValueError,'unavailable'): runtime_adapters.resolve_adapter('SET_NSGAIII')
            self.assertEqual(runtime_adapters.resolve_adapter('NSGAII')['id'],'none')

    def test_mixed_algorithms_load_only_matching_validator(self):
        _,data=self.fixture.make_experiment('mixed',algorithms=[{'class':'SET_NSGAIII'},{'class':'NSGAII'}])
        with patch.object(runtime_adapters.importlib,'import_module',side_effect=RuntimeError('adapter failed')):
            for record in data['records']:
                issues,scope=runtime_adapters.validate_record(record)
                if record['algorithm']=='NSGAII':
                    self.assertEqual(issues,[])
                    self.assertEqual(scope['adapter'],'none')
                else:
                    self.assertEqual(issues[-1]['code'],'adapter_validation_failed')
                    self.assertEqual(scope['verified_capabilities'],[])

    def test_valid_extension_reports_only_its_capabilities(self):
        _,data=self.fixture.make_experiment('adapter',algorithms=[{'class':'SET_NSGAIII'}])
        issues,scope=runtime_adapters.validate_record(data['records'][0])
        self.assertEqual(issues,[])
        self.assertEqual(scope['runtime_mechanism'],'passed')
        self.assertIn('torch_random',scope['verified_capabilities'])

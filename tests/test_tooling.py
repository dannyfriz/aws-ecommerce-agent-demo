"""Comprueba las fronteras de preparación de datos y versiones del paquete."""
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import tomllib
import unittest
from unittest.mock import MagicMock,patch

ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('seed_demo',ROOT/'scripts/seed_demo.py')
seed=importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


class ToolingTests(unittest.TestCase):
    def test_runtime_pin_matches_hashed_lock(self):
        project=tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))
        lock=(ROOT/'requirements.lock').read_text(encoding='utf-8')
        for dependency in project['project']['dependencies']:
            self.assertRegex(lock,re.escape(dependency)+r' --hash=sha256:[a-f0-9]{64}')

    def test_wrong_account_cannot_create_users_or_change_orders(self):
        with tempfile.TemporaryDirectory() as folder:
            foundation=Path(folder)/'foundation.json'
            data=Path(folder)/'data.json'
            foundation.write_text(json.dumps({'user_pool_id':{'value':'us-east-1_example'}}))
            data.write_text(json.dumps({'orders_table_arn':{'value':'arn:aws:dynamodb:us-east-1:111111111111:table/shop-demo-orders'},'orders_table_name':{'value':'shop-demo-orders'}}))
            session=MagicMock()
            session.client.return_value.get_caller_identity.return_value={'Account':'222222222222'}
            with patch.object(seed.boto3,'Session',return_value=session),patch('sys.argv',['seed','--profile','demo','--foundation',str(foundation),'--data',str(data)]):
                with self.assertRaises(SystemExit):
                    seed.main()
            session.resource.assert_not_called()
            session.client.assert_called_once_with('sts')

    def test_seed_refuses_non_lab_table_before_aws_session(self):
        with tempfile.TemporaryDirectory() as folder:
            foundation=Path(folder)/'foundation.json'
            data=Path(folder)/'data.json'
            foundation.write_text(json.dumps({'user_pool_id':{'value':'us-east-1_example'}}))
            data.write_text(json.dumps({'orders_table_arn':{'value':'arn:aws:dynamodb:us-east-1:111111111111:table/shop-prod-orders'},'orders_table_name':{'value':'shop-prod-orders'}}))
            with patch.object(seed.boto3,'Session') as session,patch('sys.argv',['seed','--profile','demo','--foundation',str(foundation),'--data',str(data)]):
                with self.assertRaises(SystemExit):
                    seed.main()
            session.assert_not_called()


if __name__=='__main__':
    unittest.main()

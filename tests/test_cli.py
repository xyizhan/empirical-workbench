import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class WorkflowTest(unittest.TestCase):
    def test_sample_and_recovery(self):
        study=ROOT/'studies/panel'
        spec=json.loads((study/'study.json').read_text())
        spec['stages'][0]['candidates']=[{'name':'bad','sql':['create table scratch(x)','select * from missing_table']},{'name':'retry','sql':['create table scratch(x)']}]
        with tempfile.TemporaryDirectory() as td:
            temp=Path(td)
            config=temp/'study.json'
            config.write_text(json.dumps(spec))
            out=temp/'run'
            subprocess.run([sys.executable,'-m','ew.cli','run',config,'--raw',study,'--out',out],check=True)
            log=json.loads((out/'run.json').read_text())
            self.assertEqual(log['attempts'][0]['outcome'],'rejected')
            self.assertEqual(log['status'],'passed')
            self.assertIn('2,-5.0',(out/'增长统计.csv').read_text())
            self.assertTrue((out/'index.html').is_file())

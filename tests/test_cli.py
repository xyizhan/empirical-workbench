import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ew import record, report, study as studies

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / 'studies/panel'
OLIST_RAW = Path(os.environ.get('OLIST_RAW', ROOT.parent / 'data/raw'))


def panel_spec():
    return json.loads((PANEL / 'study.json').read_text())


class RunCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_ew(self, spec, *extra, raw=PANEL, input=None, check=True, name='study.json'):
        config = self.dir / name
        config.write_text(json.dumps(spec, ensure_ascii=False))
        out = self.dir / ('out-' + str(len(list(self.dir.glob('out-*')))))
        proc = subprocess.run([sys.executable, '-m', 'ew.cli', 'run', str(config), '--raw', str(raw), '--out', str(out), *extra],
                              input=input, text=True, capture_output=True, cwd=ROOT)
        if check and proc.returncode:
            self.fail(proc.stderr)
        return out, proc

    def events(self, out):
        return [json.loads(line) for line in (out / 'events.jsonl').read_text().splitlines()]


class WorkflowTest(RunCase):
    def test_sample_and_recovery(self):
        spec = panel_spec()
        spec['stages'][0]['candidates'] = [{'name': 'bad', 'sql': ['create table scratch(x)', 'select * from missing_table']},
                                           {'name': 'retry', 'sql': ['create table scratch(x)']}]
        out, _ = self.run_ew(spec, '--batch')
        run = record.load(out)
        self.assertEqual(run['status'], 'passed')
        attempts = run['stages'][0]['attempts']
        self.assertEqual([(a['plan'], a['outcome']) for a in attempts], [('bad', 'rejected'), ('retry', 'accepted')])
        self.assertIn('missing_table', attempts[0]['reason'])
        # The rolled-back candidate leaves no trace; the accepted one is reported as a new table.
        self.assertEqual(run['stages'][0]['tables'], [dict(name='scratch', change='created', rows=0, columns=['x'])])
        self.assertIn('2,-5.0', (out / '增长统计.csv').read_text())
        self.assertTrue((out / 'index.html').is_file())

    def test_interactive_decision_reaches_sql(self):
        spec = panel_spec()
        spec['decisions'] = {'mode': {'options': ['first', 'second'], 'value': 'first'}}
        spec['stages'][0]['decision'] = 'mode'
        spec['stages'][-1]['exports']['choice.csv'] = 'select value from decision'
        out, proc = self.run_ew(spec, '--interactive', input='invalid\n2\n')
        self.assertIn('请从上列选项中选择', proc.stdout)
        self.assertEqual((out / 'choice.csv').read_text().splitlines(), ['value', 'second'])
        run = record.load(out)
        self.assertEqual(run['decisions']['mode']['source'], 'interactive')
        self.assertEqual(run['stages'][0]['decision'], dict(name='mode', value='second', source='interactive'))

    def test_command_line_decision_is_validated(self):
        spec = panel_spec()
        spec['decisions'] = {'mode': {'options': ['first', 'second'], 'value': 'first'}}
        spec['stages'][0]['decision'] = 'mode'
        _, proc = self.run_ew(spec, '--batch', '--decision', 'mode=third', check=False)
        self.assertEqual(proc.returncode, 2)
        self.assertIn('first, second', proc.stderr)


class RecordContractTest(RunCase):
    def test_run_record_shape(self):
        out, _ = self.run_ew(panel_spec(), '--batch')
        run = record.load(out)
        self.assertEqual(run['schema'], 'ew.run/1')
        self.assertEqual(run['study']['question'], panel_spec()['question'])
        self.assertEqual(run['sources']['raw']['rows'], 8)
        self.assertEqual(run['sources']['raw']['columns'], ['firm', 'year', 'revenue'])
        self.assertEqual([s['status'] for s in run['stages']], ['passed'] * 5)
        flow = {t['name']: t['rows'] for s in run['stages'] for t in s['tables']}
        self.assertEqual(flow, {'base': 8, 'qc': 8, 'analysis': 8})
        exports = {e['file']: e['rows'] for s in run['stages'] for e in s['exports']}
        self.assertEqual(exports['分析表.csv'], 8)
        self.assertIsNotNone(run['finished_at'])

    def test_event_stream(self):
        out, _ = self.run_ew(panel_spec(), '--batch')
        events = self.events(out)
        self.assertEqual([e['seq'] for e in events], list(range(1, len(events) + 1)))
        self.assertTrue(all(e['kind'] in record.EVENTS for e in events))
        self.assertEqual(events[0]['kind'], 'run.start')
        self.assertEqual(events[-1]['kind'], 'run.end')
        sql = [e for e in events if e['kind'] == 'sql']
        self.assertEqual(sql[0]['stage'], '2 匹配相邻年度')

    def test_failed_check_stops_run(self):
        spec = panel_spec()
        spec['stages'][1]['checks']['收入为正'] = 'select firm, year, revenue from base where revenue*1.0 <= 0'
        out, proc = self.run_ew(spec, '--batch', check=False)
        self.assertNotEqual(proc.returncode, 0)
        run = record.load(out)
        self.assertEqual(run['status'], 'failed')
        self.assertEqual([s['status'] for s in run['stages']], ['passed', 'failed', 'pending', 'pending', 'pending'])
        check = run['stages'][1]['attempts'][0]['checks'][-1]
        self.assertFalse(check['passed'])
        self.assertEqual(check['columns'], ['firm', 'year', 'revenue'])
        self.assertEqual(check['violations'], len(check['examples']))
        self.assertTrue((out / 'index.html').is_file())

    def test_warning_check_does_not_stop(self):
        spec = panel_spec()
        spec['stages'][1]['checks']['收入为正'] = {'sql': 'select * from base where revenue*1.0 <= 0', 'severity': 'warn'}
        out, _ = self.run_ew(spec, '--batch')
        run = record.load(out)
        self.assertEqual(run['status'], 'passed')
        check = run['stages'][1]['attempts'][0]['checks'][-1]
        self.assertEqual((check['severity'], check['passed']), ('warn', False))
        self.assertGreater(check['violations'], 0)
        self.assertIn('check.warn', {e['kind'] for e in self.events(out)})

    def test_missing_decision_pauses(self):
        spec = panel_spec()
        spec['decisions'] = {'mode': {'options': ['first', 'second']}}
        spec['stages'][2]['decision'] = 'mode'
        out, proc = self.run_ew(spec, '--batch', check=False)
        self.assertNotEqual(proc.returncode, 0)
        run = record.load(out)
        self.assertEqual(run['status'], 'needs_decision')
        self.assertEqual(run['stages'][2]['status'], 'needs_decision')
        self.assertIn('mode', run['reason'])

    def test_tools_are_recorded(self):
        spec = panel_spec()
        script = self.dir / 'tool.py'
        script.write_text('import json,sys,pathlib\nrun=json.loads((pathlib.Path(sys.argv[1])/"run.json").read_text())\nprint(run["status"], len(run["stages"]))\n')
        spec['tools'] = {'recheck': {'argv': ['{python}', str(script), '{out}'], 'label': '独立复算'}}
        out, _ = self.run_ew(spec, '--batch')
        tool = record.load(out)['tools'][0]
        self.assertEqual((tool['name'], tool['label'], tool['returncode']), ('recheck', '独立复算', 0))
        self.assertEqual((out / tool['log']).read_text().strip(), 'running 5')


class StudyValidationTest(unittest.TestCase):
    def test_reports_every_problem(self):
        spec = panel_spec()
        spec['stagse'] = []
        spec['stages'][0]['decision'] = 'undeclared'
        spec['stages'][1]['checks'] = {'x': {'sql': 'select 1', 'severity': 'fatal'}}
        spec['stages'][2]['exports'] = {'../escape.csv': 'select 1'}
        with self.assertRaises(studies.StudyError) as ctx:
            studies.normalize(spec)
        text = '\n'.join(ctx.exception.problems)
        for fragment in ('stagse', 'undeclared', 'severity', '../escape.csv'):
            self.assertIn(fragment, text)

    def test_normalize_is_idempotent(self):
        spec = studies.load(ROOT / 'studies/olist/study.json')
        self.assertEqual(studies.normalize(spec), spec)

    def test_validate_command(self):
        proc = subprocess.run([sys.executable, '-m', 'ew.cli', 'validate', str(PANEL / 'study.json')], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('5 个阶段', proc.stdout)


class ReportTest(RunCase):
    def test_generic_report_source(self):
        out, _ = self.run_ew(panel_spec(), '--batch')
        source = report.write_source(out).read_text()
        self.assertIn(panel_spec()['title'], source)
        self.assertIn('### 增长统计', source)
        self.assertEqual(record.load(out)['report']['builder'], 'tabular')

    def test_study_report_builder(self):
        spec = panel_spec()
        (self.dir / 'report.py').write_text('def build(out, run):\n    return "# " + run["study"]["title"] + " " + run["status"]\n')
        spec['report'] = {'builder': 'report.py'}
        out, _ = self.run_ew(spec, '--batch')
        self.assertEqual(report.write_source(out).read_text(), f'# {spec["title"]} passed')

    def test_report_requires_passed_run(self):
        spec = panel_spec()
        spec['stages'][1]['checks']['失败'] = 'select 1'
        out, _ = self.run_ew(spec, '--batch', check=False)
        with self.assertRaises(ValueError):
            report.write_source(out)


@unittest.skipUnless((OLIST_RAW / 'olist_orders_dataset.csv').is_file(), 'Olist CSVs not available (set OLIST_RAW)')
class OlistTest(RunCase):
    def test_olist_run_verifies(self):
        spec = json.loads((ROOT / 'studies/olist/study.json').read_text())
        spec['tools']['verify']['argv'][1] = str(ROOT / 'studies/olist/verify.py')
        spec['report']['builder'] = str(ROOT / 'studies/olist/report.py')
        out, _ = self.run_ew(spec, '--batch', raw=OLIST_RAW)
        run = record.load(out)
        self.assertEqual(run['status'], 'passed')
        self.assertEqual([a['outcome'] for a in run['stages'][1]['attempts']], ['rejected', 'accepted'])
        self.assertIn('通过', (out / 'verify.log').read_text())
        self.assertIn('包裹晚到', report.write_source(out).read_text())


if __name__ == '__main__':
    unittest.main()

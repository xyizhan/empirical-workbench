import json
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ew.server import Workbench, make_handler

ROOT = Path(__file__).resolve().parents[1]


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        studies = Path(cls.tmp.name) / 'studies'
        shutil.copytree(ROOT / 'studies/panel', studies / 'panel')
        spec = json.loads((studies / 'panel/study.json').read_text())
        spec['decisions'] = {'mode': {'options': ['first', 'second'], 'value': 'first'}}
        spec['stages'][2]['decision'] = 'mode'
        (studies / 'panel/study.json').write_text(json.dumps(spec, ensure_ascii=False))
        cls.raw = str(studies / 'panel')
        cls.bench = Workbench(Path(cls.tmp.name) / 'runs', studies)
        web = Path(cls.tmp.name) / 'web'
        web.mkdir()
        (web / 'index.html').write_text('<!doctype html><title>ok</title>')
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(cls.bench, web))
        cls.base = f'http://127.0.0.1:{cls.httpd.server_address[1]}'
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        for job in cls.bench.jobs.values():
            job['proc'].wait(timeout=60)
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def call(self, path, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        request = Request(self.base + path, data=data, headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            with urlopen(request) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def wait(self, run_id):
        for _ in range(200):
            status, detail = self.call(f'/api/runs/{run_id}')
            if detail.get('run') and detail['run']['status'] != 'running':
                return detail
            time.sleep(0.05)
        self.fail('run did not finish')

    def test_pause_then_decide(self):
        _, studies = self.call('/api/studies')
        self.assertEqual(studies[0]['decisions']['mode']['options'], ['first', 'second'])
        status, started = self.call('/api/runs', {'study': 'panel', 'raw': self.raw, 'decisions': {'mode': ''}})
        self.assertEqual(status, 200, started)
        detail = self.wait(started['id'])
        self.assertEqual(detail['run']['status'], 'needs_decision')
        self.assertEqual(detail['study_id'], 'panel')
        _, started = self.call('/api/runs', {'study': 'panel', 'raw': self.raw, 'decisions': {'mode': 'second'}})
        detail = self.wait(started['id'])
        self.assertEqual(detail['run']['status'], 'passed')
        run_id = started['id']
        _, result = self.call(f'/api/runs/{run_id}/query', {'sql': 'select value from decision'})
        self.assertEqual(result['rows'], [['second']])
        status, _ = self.call(f'/api/runs/{run_id}/query', {'sql': 'drop table analysis'})
        self.assertEqual(status, 400)
        _, preview = self.call(f'/api/runs/{run_id}/preview/%E5%88%86%E6%9E%90%E8%A1%A8.csv?limit=3')
        self.assertEqual(len(preview['rows']), 3)
        _, events = self.call(f'/api/runs/{run_id}/events?after=0')
        self.assertEqual(events[-1]['kind'], 'run.end')
        _, runs = self.call('/api/runs')
        self.assertEqual({r['status'] for r in runs}, {'passed', 'needs_decision'})

    def test_rejects_bad_requests(self):
        status, body = self.call('/api/runs', {'study': 'panel', 'raw': '/no/such/dir'})
        self.assertEqual(status, 400)
        self.assertIn('不存在', body['error'])
        status, _ = self.call('/api/runs', {'study': 'panel', 'raw': self.raw, 'decisions': {'mode': 'third'}})
        self.assertEqual(status, 400)
        status, _ = self.call('/api/runs', {'study': 'panel', 'raw': self.raw}, {'Origin': 'http://evil.example'})
        self.assertEqual(status, 403)
        status, _ = self.call('/api/runs/..%2F..%2Fetc')
        self.assertEqual(status, 404)
        status, _ = self.call('/api/runs/x', {}, {'Content-Type': 'text/plain'})
        self.assertIn(status, (404, 415))


if __name__ == '__main__':
    unittest.main()

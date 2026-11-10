import io as stdio
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from rich.console import Console

from ew import project, record
from ew.agent import Chat

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / 'studies/panel'

BASE = {
    'sources': {'panel': {'file': 'panel.csv'}},
    'stages': [{'name': '1 企业年度粒度', 'sql': ['create table fy as select * from panel'],
                'checks': {'企业年度唯一': 'select firm, year from fy group by 1, 2 having count(*) > 1'},
                'exports': {'规模.csv': 'select count(*) n from fy'}}],
}
TOPIC_STAGES = [{'name': '1 增长率', 'sql': ['create table g as select a.firm, a.year, a.revenue*1.0/b.revenue-1 growth from fy a join fy b on a.firm=b.firm and a.year=b.year+1 where b.revenue<>0'],
                 'exports': {'增长率.csv': 'select * from g order by firm, year'}}]


def ew(*args):
    return subprocess.run([sys.executable, '-m', 'ew.cli', *map(str, args)], capture_output=True, text=True, cwd=ROOT)


class ProjectCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = project.create(Path(self.tmp.name) / 'p', PANEL, '示例面板')
        record.save_json(self.root / 'base.json', BASE)

    def tearDown(self):
        self.tmp.cleanup()


class ProjectTest(ProjectCase):
    def test_create_registers_sources(self):
        spec = json.loads((self.root / 'base.json').read_text())
        self.assertIn('panel', spec['sources'])
        fresh = project.create(Path(self.tmp.name) / 'q', PANEL)
        self.assertEqual(json.loads((fresh / 'base.json').read_text()), {'sources': {'panel': {'file': 'panel.csv'}}, 'stages': []})
        self.assertEqual(project.state(fresh)['base']['stages'], [])

    def test_topic_needs_confirmed_card_and_reuses_base(self):
        self.assertEqual(ew('run', self.root, '--batch').returncode, 0)
        project.save_topic(self.root, 'growth', {'card': {'title': '增长', 'question': '增长率', 'status': 'draft'}, 'stages': TOPIC_STAGES})
        proc = ew('run', self.root, '--topic', 'growth', '--batch')
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('尚未经研究者确认', proc.stderr)
        project.save_topic(self.root, 'growth', {'card': {'title': '增长', 'question': '增长率', 'status': 'confirmed'}, 'stages': TOPIC_STAGES})
        proc = ew('run', self.root, '--topic', 'growth', '--batch')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        latest = project.latest(self.root, 'growth')
        run = latest['run']
        self.assertEqual(run['status'], 'passed')
        self.assertEqual(Path(run['base']['run']), project.latest(self.root, 'base')['dir'])
        self.assertEqual(run['sources']['fy']['rows'], 8)
        self.assertTrue((latest['dir'] / '增长率.csv').is_file())
        self.assertEqual(len([r for r in project.runs(self.root) if r['kind'] == 'base']), 1)
        self.assertEqual(project.state(self.root)['topics'][0]['last_run']['status'], 'passed')


class FakeClient:
    """Plays back scripted assistant messages; records what the model was sent."""
    model = 'fake'

    def __init__(self, turns):
        self.turns = list(turns)
        self.sent = []

    def chat(self, messages, tools=None):
        self.sent.append(messages)
        calls = self.turns.pop(0)
        if isinstance(calls, str):
            return {'role': 'assistant', 'content': calls}
        return {'role': 'assistant', 'content': '', 'tool_calls': [
            {'id': f'c{i}', 'type': 'function', 'function': {'name': n, 'arguments': json.dumps(a, ensure_ascii=False)}}
            for i, (n, a) in enumerate(calls)]}


class AgentTest(ProjectCase):
    def chat(self, client, answers):
        answers = list(answers)
        console = Console(file=stdio.StringIO(), width=100)
        return Chat(self.root, client=client, console=console, ask=lambda prompt: answers.pop(0))

    def test_research_flow_with_confirmation_gate(self):
        card = {'title': '收入增长', 'question': '企业收入增长率如何分布？', 'unit': '企业年度'}
        client = FakeClient([
            [('inspect_data', {}), ('query', {'sql': 'select count(*) n from panel', 'target': 'raw'})],
            [('write_base', {'spec': BASE}), ('run', {'target': 'base'})],
            [('propose_topic', {'slug': 'growth', 'card': card})],
            [('write_topic', {'slug': 'growth', 'stages': TOPIC_STAGES})],
            [('propose_topic', {'slug': 'growth', 'card': card})],
            [('write_topic', {'slug': 'growth', 'stages': TOPIC_STAGES}), ('run', {'target': 'growth'}),
             ('query', {'sql': 'select count(*) from g', 'target': 'topic:growth'})],
            '完成。',
        ])
        chat = self.chat(client, ['我想先看看。', 'y'])
        chat.reply('开始')
        sent = [json.loads(m['content']) if m['content'][:1] in '{[' else m['content'] for m in client.sent[-1] if m['role'] == 'tool']
        inspect, count, base_written, base_run, first_card, refused, confirmed, topic_written, topic_run, topic_count = sent
        self.assertEqual(inspect['panel']['rows'], 8)
        self.assertIn('8', count)
        self.assertTrue(base_written['saved'])
        self.assertEqual(base_run['status'], 'passed')
        self.assertEqual(first_card, {'slug': 'growth', 'status': 'draft', 'researcher_feedback': '我想先看看。'})
        self.assertFalse(refused['saved'])
        self.assertEqual(confirmed['status'], 'confirmed')
        self.assertTrue(topic_written['saved'])
        self.assertEqual(topic_run['status'], 'passed')
        self.assertTrue(topic_count.startswith('count_star()'), topic_count)
        self.assertTrue((self.root / '.ew/chat.json').is_file())

    def test_model_cannot_confirm_card_itself(self):
        client = FakeClient([[('propose_topic', {'slug': 'x', 'card': {'title': 't', 'question': 'q', 'status': 'confirmed'}})], '好'])
        self.chat(client, ['']).reply('开始')
        topic, _ = project.load_topic(self.root, 'x')
        self.assertEqual(topic['card']['status'], 'draft')

    def test_researcher_chooses_decision_values(self):
        self.assertEqual(ew('run', self.root, '--batch').returncode, 0)
        stages = [dict(TOPIC_STAGES[0], decision='mode'), {'name': '2 记录口径', 'exports': {'口径.csv': 'select value from decision'}}]
        project.save_topic(self.root, 'growth', {'card': {'title': '增长', 'question': 'q', 'status': 'confirmed'}, 'stages': stages,
                                                 'decisions': {'mode': {'options': ['first', 'second'], 'value': None}}})
        client = FakeClient([[('run', {'target': 'growth', 'decisions': {'mode': 'second'}})],
                             [('run', {'target': 'growth', 'decisions': {'mode': 'second'}})], '好'])
        prompts = []
        answers = ['先别跑', 'first']
        chat = Chat(self.root, client=client, console=Console(file=stdio.StringIO()), ask=lambda p: prompts.append(p) or answers.pop(0))
        chat.reply('开始')
        refused, ran = [json.loads(m['content']) for m in client.sent[-1] if m['role'] == 'tool']
        self.assertEqual(refused['researcher_feedback'], '先别跑')
        self.assertFalse(refused['started'])
        self.assertEqual(ran['status'], 'passed')
        self.assertEqual(ran['stages'][0]['decision']['value'], 'first')
        self.assertIn('first', prompts[0])
        self.assertEqual(len([r for r in project.runs(self.root) if r['kind'] == 'growth']), 1)

    def test_errors_go_back_to_model(self):
        client = FakeClient([[('query', {'sql': 'select * from nope', 'target': 'raw'}), ('run', {'target': 'missing-topic'})], '好'])
        self.chat(client, []).reply('开始')
        query, run = [json.loads(m['content']) for m in client.sent[-1] if m['role'] == 'tool']
        self.assertIn('nope', query['error'])
        self.assertIn('没有选题', run['error'])


if __name__ == '__main__':
    unittest.main()


class LLMClientTest(unittest.TestCase):
    def test_retries_truncated_response(self):
        import http.client
        from unittest import mock
        from ew import llm

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return json.dumps({'choices': [{'message': {'role': 'assistant', 'content': '好'}}]}).encode()

        calls = [http.client.IncompleteRead(b''), Response()]

        def urlopen(request, timeout):
            item = calls.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with mock.patch.object(llm.urllib.request, 'urlopen', urlopen), mock.patch.object(llm.time, 'sleep', lambda s: None):
            message = llm.Client(api_key='test').chat([{'role': 'user', 'content': 'hi'}])
        self.assertEqual(message['content'], '好')
        self.assertEqual(calls, [])

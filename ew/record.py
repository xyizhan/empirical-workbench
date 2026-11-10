"""The run record (run.json, schema ew.run/1) and its event stream (events.jsonl).

Viewers, report builders, tools and AI agents read these two files; see docs/run-format.md.
"""
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__

SCHEMA = 'ew.run/1'

# Run status values.
RUNNING, PASSED, FAILED, NEEDS_DECISION, INTERRUPTED = 'running', 'passed', 'failed', 'needs_decision', 'interrupted'

# Event kinds and their Chinese display labels.
EVENTS = {
    'run.start': '研究问题',
    'source.load': '读取',
    'source.loaded': '已读取',
    'stage.start': '阶段',
    'plan.start': '执行方案',
    'sql': 'SQLite',
    'check.start': '核验',
    'check.pass': '通过',
    'check.warn': '提醒',
    'check.fail': '未通过',
    'plan.rollback': '已回滚',
    'plan.accept': '采用方案',
    'export': '生成',
    'decision.made': '采用口径',
    'stage.end': '阶段完成',
    'evidence': '展示证据',
    'tool.start': '调用工具',
    'tool.end': '工具结果',
    'report.start': '生成报告',
    'report.done': '报告完成',
    'run.end': '运行结束',
}


class Interrupted(Exception):
    """The researcher or presenter stopped the run."""


class DecisionRequired(Exception):
    """A research decision has no value; the run pauses for the researcher."""


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def save_json(path, value):
    tmp = Path(path).with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
    tmp.replace(path)


def new_run(study_path, spec, raw):
    """Build the initial run record; every declared stage starts as pending."""
    return {
        'schema': SCHEMA,
        'ew_version': __version__,
        'status': RUNNING,
        'reason': None,
        'started_at': now(),
        'finished_at': None,
        'duration_s': None,
        'study': {
            'path': str(study_path),
            'dir': str(Path(study_path).parent),
            'sha256': sha256(study_path),
            'title': spec.get('title') or spec.get('guide', {}).get('title') or Path(study_path).parent.name,
            'question': spec.get('question', ''),
            'unit': spec.get('unit', ''),
        },
        'raw': str(raw),
        'sources': {},
        'stages': [dict(name=s['name'], description=s.get('description', ''), status='pending',
                        attempts=[], exports=[], tables=[], duration_s=None) for s in spec['stages']],
        'decisions': spec['decisions'],
        'tools': [],
        'report': None,
    }


class Recorder:
    """Owns run.json and events.jsonl in a run directory and notifies live listeners."""

    def __init__(self, out, run, listeners=()):
        self.out = Path(out)
        self.run = run
        self.listeners = list(listeners)
        self.seq = 0
        self.stage = None
        self.clock = time.perf_counter()
        self.events = (self.out / 'events.jsonl').open('a', encoding='utf-8')

    def emit(self, kind, message='', **data):
        if kind not in EVENTS:
            raise ValueError(f'Unknown event kind {kind!r}')
        if kind == 'stage.start':
            self.stage = message
        self.seq += 1
        event = dict(seq=self.seq, ts=now(), kind=kind, stage=self.stage, message=str(message))
        if data:
            event['data'] = data
        self.events.write(json.dumps(event, ensure_ascii=False, default=str) + '\n')
        self.events.flush()
        for listener in self.listeners:
            listener(event)
        return event

    def save(self):
        save_json(self.out / 'run.json', self.run)

    def finish(self, status, reason=None):
        self.run.update(status=status, reason=reason, finished_at=now(),
                        duration_s=round(time.perf_counter() - self.clock, 3))
        self.emit('run.end', status, status=status, reason=reason)
        self.save()
        self.events.close()


def load(out):
    run = json.loads((Path(out) / 'run.json').read_text(encoding='utf-8'))
    if run.get('schema') != SCHEMA:
        raise ValueError(f'{out}: 运行记录格式为 {run.get("schema")!r}，本版本读取 {SCHEMA}；请用当前版本重新运行')
    return run


def stage_names(run):
    return [s['name'] for s in run['stages']]

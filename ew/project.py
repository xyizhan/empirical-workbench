"""Research projects: one topic-independent data base plus any number of research topics.

PROJECT/
  project.json          {"schema": "ew.project/1", "name", "raw", "created_at"}
  base.json             study spec for the data base (sources + base stages); flags, never drops
  profile.md            data profile written with the researcher (what the data is, what it could study)
  topics/<slug>.json    {"card": {...status: draft|confirmed}, "decisions", "stages", "tools", "report"}
  runs/                 base-<ts>/ and <slug>-<ts>/ run directories
  .ew/                  chat session state

A topic run copies the tables of the latest passed base run, so topics can be added or
switched without re-running the base. Topics cannot run before their card is confirmed.
"""
import json
import re
from datetime import datetime
from pathlib import Path

from . import io, record, study as studies

SCHEMA = 'ew.project/1'
CARD_FIELDS = {
    'title': '题目',
    'question': '研究问题',
    'unit': '分析单位',
    'outcome': '被解释变量',
    'explanatory': '核心解释变量',
    'controls': '控制变量与异质性',
    'sample': '样本范围',
    'pending': '待定口径',
    'rationale': '为什么这份数据能回答',
}


class ProjectError(ValueError):
    pass


def is_project(path):
    return (Path(path) / 'project.json').is_file()


def meta(project):
    return json.loads((Path(project) / 'project.json').read_text(encoding='utf-8'))


def raw_dir(project):
    raw = Path(meta(project)['raw'])
    return raw if raw.is_absolute() else (Path(project) / raw).resolve()


def table_name(stem):
    name = re.sub(r'\W+', '_', stem.lower()).strip('_') or 'source'
    return 't_' + name if name[0].isdigit() else name


def source_files(raw):
    return sorted(p for p in Path(raw).iterdir()
                  if p.is_file() and not p.name.startswith('.') and p.suffix.lower() in io.TEXT + io.PANDAS + ('.parquet',))


def create(project, raw, name=None):
    project, raw = Path(project).resolve(), Path(raw).resolve()
    if is_project(project):
        raise ProjectError(f'{project} 已经是研究项目')
    if not raw.is_dir():
        raise ProjectError(f'原始数据目录不存在：{raw}')
    files = source_files(raw)
    if not files:
        raise ProjectError(f'{raw} 中没有可读取的数据文件（csv/tsv/txt/parquet/xlsx/dta）')
    project.mkdir(parents=True, exist_ok=True)
    (project / 'topics').mkdir(exist_ok=True)
    (project / 'runs').mkdir(exist_ok=True)
    record.save_json(project / 'project.json', dict(schema=SCHEMA, name=name or project.name, raw=str(raw),
                                                    created_at=record.now()))
    sources = {}
    for path in files:
        table = table_name(path.stem)
        while table in sources:
            table += '_'
        sources[table] = dict(file=path.name)
    record.save_json(project / 'base.json', dict(sources=sources, stages=[]))
    return project


def base_spec(project):
    path = Path(project) / 'base.json'
    spec = studies.load(path)
    spec['title'] = f'{meta(project)["name"]} · 数据底座'
    spec.setdefault('question', '')
    return spec, path


def topic_path(project, slug):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,40}', slug or ''):
        raise ProjectError('选题标识只能用字母、数字、- 和 _，例如 late-delivery')
    return Path(project) / 'topics' / f'{slug}.json'


def load_topic(project, slug):
    path = topic_path(project, slug)
    if not path.is_file():
        raise ProjectError(f'没有选题 {slug}')
    return json.loads(path.read_text(encoding='utf-8')), path


def save_topic(project, slug, topic):
    record.save_json(topic_path(project, slug), topic)


def topics(project):
    items = []
    for path in sorted((Path(project) / 'topics').glob('*.json')):
        topic = json.loads(path.read_text(encoding='utf-8'))
        items.append(dict(slug=path.stem, **topic))
    return items


def runs(project):
    """All runs of the project, newest first, with kind 'base' or the topic slug."""
    items = []
    for path in (Path(project) / 'runs').glob('*/run.json'):
        try:
            run = record.load(path.parent)
        except ValueError:
            continue
        study_path = Path(run['study']['path'])
        kind = 'base' if study_path.name == 'base.json' else study_path.stem
        items.append(dict(id=path.parent.name, dir=path.parent, kind=kind, status=run['status'],
                          started_at=run['started_at'], run=run))
    return sorted(items, key=lambda r: r['started_at'], reverse=True)


def latest(project, kind, passed=False):
    for item in runs(project):
        if item['kind'] == kind and (not passed or item['status'] == record.PASSED):
            return item
    return None


def topic_spec(project, slug, base_run=None):
    topic, path = load_topic(project, slug)
    card = topic.get('card') or {}
    if card.get('status') != 'confirmed':
        raise ProjectError(f'选题 {slug} 的选题卡尚未经研究者确认，不能构造变量')
    if base_run is None:
        found = latest(project, 'base', passed=True)
        if not found:
            raise ProjectError('还没有通过核验的底座运行，请先运行底座')
        base_run = found['dir']
    spec = dict(title=f'{meta(project)["name"]} · 选题：{card.get("title") or slug}', question=card.get('question', ''),
                unit=card.get('unit', ''), base=dict(run=str(Path(base_run).resolve())), card=card,
                sources={}, decisions=topic.get('decisions', {}), stages=topic.get('stages', []),
                tools=topic.get('tools', {}))
    if topic.get('report'):
        spec['report'] = topic['report']
    return studies.normalize(spec, base=path.parent, path=path), path


def new_out(project, label):
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    out, n = Path(project) / 'runs' / f'{label}-{stamp}', 1
    while out.exists():
        n += 1
        out = Path(project) / 'runs' / f'{label}-{stamp}-{n}'
    return out


def clip(value, limit=160):
    text = str(value)
    return text if len(text) <= limit else text[:limit] + '…'


def summarize(run):
    """A compact, model-friendly digest of a run record."""
    stages = []
    for stage in run['stages']:
        item = dict(name=stage['name'], status=stage['status'])
        attempts = []
        for attempt in stage['attempts']:
            checks = [dict(name=c['name'], severity=c['severity'], violations=c['violations'], columns=c['columns'],
                           examples=[[clip(v, 40) for v in row] for row in c['examples'][:3]])
                      for c in attempt['checks'] if not c['passed']]
            attempts.append(dict(plan=attempt['plan'], outcome=attempt['outcome'],
                                 reason=clip(attempt['reason'], 400) if attempt['reason'] else None,
                                 passed_checks=sum(c['passed'] for c in attempt['checks']), problems=checks))
        item['attempts'] = attempts
        item['tables'] = [dict(name=t['name'], change=t['change'], rows=t.get('rows'), rows_before=t.get('rows_before'),
                               columns=len(t.get('columns') or [])) for t in stage['tables']]
        item['exports'] = [dict(file=e['file'], rows=e['rows']) for e in stage['exports']]
        if stage.get('decision'):
            item['decision'] = stage['decision']
        stages.append(item)
    return dict(status=run['status'], reason=clip(run['reason'], 600) if run['reason'] else None,
                sources={k: dict(rows=v['rows'], columns=len(v['columns'])) for k, v in run['sources'].items()},
                stages=stages, tools=[dict(name=t['name'], returncode=t['returncode']) for t in run['tools']])


def state(project):
    """What exists in the project right now, for the agent and the CLI."""
    project = Path(project)
    base, _ = base_spec(project)
    base_run = latest(project, 'base')
    items = []
    for topic in topics(project):
        last = latest(project, topic['slug'])
        items.append(dict(slug=topic['slug'], title=(topic.get('card') or {}).get('title'),
                          card_status=(topic.get('card') or {}).get('status', 'draft'), stages=[s.get('name') for s in topic.get('stages', [])],
                          last_run=dict(id=last['id'], status=last['status']) if last else None))
    profile = project / 'profile.md'
    return dict(name=meta(project)['name'], raw=str(raw_dir(project)),
                files=[p.name for p in source_files(raw_dir(project))],
                base=dict(sources=list(base['sources']), stages=[s['name'] for s in base['stages']],
                          last_run=dict(id=base_run['id'], status=base_run['status']) if base_run else None),
                profile=profile.read_text(encoding='utf-8')[:1500] if profile.is_file() else None, topics=items)

"""Load, validate and normalize a study specification (study.json)."""
import json
import re
from pathlib import Path

STUDY_KEYS = {'title', 'question', 'unit', 'description', 'sources', 'decisions', 'stages', 'tools', 'report', 'guide'}
STAGE_KEYS = {'name', 'description', 'sql', 'candidates', 'checks', 'exports', 'decision', 'classroom'}
SEVERITIES = ('error', 'warn')


class StudyError(ValueError):
    """A study specification that cannot run; .problems lists every issue found."""

    def __init__(self, path, problems):
        self.problems = problems
        super().__init__(f'{path}: 研究配置有 {len(problems)} 处问题\n' + '\n'.join('  - ' + p for p in problems))


def ident(name):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', name):
        raise ValueError(f'Invalid SQL identifier {name!r}')
    return '"' + name + '"'


def _sql_list(value, where, problems):
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list) or not all(isinstance(s, str) for s in value):
        problems.append(f'{where} 应为 SQL 字符串或字符串数组')
        return []
    return value


def _check(name, value, where, problems):
    if isinstance(value, str):
        return dict(name=name, sql=value, severity='error', description='')
    if isinstance(value, dict) and isinstance(value.get('sql'), str):
        severity = value.get('severity', 'error')
        if severity not in SEVERITIES:
            problems.append(f'{where} 的 severity 只能是 error 或 warn')
        unknown = set(value) - {'sql', 'severity', 'description'}
        if unknown:
            problems.append(f'{where} 含未知字段 {", ".join(sorted(unknown))}')
        return dict(name=name, sql=value['sql'], severity=severity, description=value.get('description', ''))
    problems.append(f'{where} 应为 SQL 字符串，或包含 sql 的对象')
    return None


def normalize(spec, base=None, path='study.json'):
    """Return a normalized copy of spec, raising StudyError with all problems found.

    Normalized form: every stage has candidates (list of {name, sql}), checks (list of
    {name, sql, severity, description}) and exports (dict); tools map name -> {argv, label}.
    Normalizing an already normalized spec gives the same result.
    """
    problems = []
    if not isinstance(spec, dict):
        raise StudyError(path, ['顶层应为 JSON 对象'])
    spec = json.loads(json.dumps(spec))
    unknown = set(spec) - STUDY_KEYS
    if unknown:
        problems.append(f'未知顶层字段 {", ".join(sorted(unknown))}（可用：{", ".join(sorted(STUDY_KEYS))}）')

    sources = spec.get('sources')
    if not isinstance(sources, dict) or not sources:
        problems.append('sources 应为非空对象：表名 → {file, columns}')
        sources = {}
    for table, source in sources.items():
        try:
            ident(table)
        except ValueError:
            problems.append(f'sources.{table}：表名只能用字母、数字和下划线，且不能以数字开头')
        if not isinstance(source, dict) or not isinstance(source.get('file'), str):
            problems.append(f'sources.{table} 缺少 file')
            continue
        columns = source.get('columns')
        if not isinstance(columns, list) or not columns:
            problems.append(f'sources.{table}.columns 应为非空字段名数组')
            continue
        for column in columns:
            try:
                ident(column)
            except (ValueError, TypeError):
                problems.append(f'sources.{table}.columns：字段名 {column!r} 不是合法标识符')

    decisions = spec.setdefault('decisions', {})
    if not isinstance(decisions, dict):
        problems.append('decisions 应为对象：口径名 → {options, value}')
        decisions = spec['decisions'] = {}
    for name, decision in decisions.items():
        if not isinstance(decision, dict) or not isinstance(decision.get('options'), list) or not decision['options']:
            problems.append(f'decisions.{name}.options 应为非空数组')
            continue
        if decision.get('value') is not None and decision['value'] not in decision['options']:
            problems.append(f'decisions.{name}.value 不在 options 中')
        decision.setdefault('value', None)
        decision.setdefault('source', 'default')

    stages = spec.get('stages')
    if not isinstance(stages, list) or not stages:
        problems.append('stages 应为非空数组')
        stages = []
    seen = set()
    for index, stage in enumerate(stages, 1):
        where = f'stages[{index}]'
        if not isinstance(stage, dict) or not isinstance(stage.get('name'), str) or not stage['name'].strip():
            problems.append(f'{where} 缺少 name')
            continue
        where = f'阶段「{stage["name"]}」'
        if stage['name'] in seen:
            problems.append(f'{where} 重名')
        seen.add(stage['name'])
        unknown = set(stage) - STAGE_KEYS
        if unknown:
            problems.append(f'{where} 含未知字段 {", ".join(sorted(unknown))}（可用：{", ".join(sorted(STAGE_KEYS))}）')
        if 'candidates' in stage and stage.get('sql'):
            problems.append(f'{where} 不能同时写 sql 与 candidates')
        if 'candidates' in stage:
            stage.pop('sql', None)
        candidates = stage.get('candidates')
        if candidates is None:
            candidates = [dict(name='main', sql=_sql_list(stage.pop('sql', []), f'{where}.sql', problems))]
        elif not isinstance(candidates, list) or not candidates:
            problems.append(f'{where}.candidates 应为非空数组')
            candidates = []
        else:
            names = [c.get('name') if isinstance(c, dict) else None for c in candidates]
            if not all(isinstance(n, str) and n for n in names) or len(set(names)) != len(names):
                problems.append(f'{where}.candidates 每项需要唯一的 name')
            candidates = [dict(name=c.get('name'), sql=_sql_list(c.get('sql', []), f'{where} 候选「{c.get("name")}」', problems))
                          for c in candidates if isinstance(c, dict)]
        stage['candidates'] = candidates
        checks = stage.get('checks', {})
        if isinstance(checks, dict):
            checks = [_check(n, v, f'{where} 核验「{n}」', problems) for n, v in checks.items()]
        elif isinstance(checks, list):
            items = checks
            checks = []
            for c in items:
                if isinstance(c, dict) and c.get('name'):
                    rest = {k: v for k, v in c.items() if k != 'name'}
                    checks.append(_check(c['name'], rest, f'{where} 核验「{c["name"]}」', problems))
                else:
                    problems.append(f'{where}.checks 列表项需要 name')
        else:
            problems.append(f'{where}.checks 应为对象或数组')
            checks = []
        stage['checks'] = [c for c in checks if c]
        exports = stage.setdefault('exports', {})
        if not isinstance(exports, dict) or not all(isinstance(v, str) for v in exports.values()):
            problems.append(f'{where}.exports 应为对象：文件名 → SQL')
        for file in exports if isinstance(exports, dict) else ():
            if '/' in file or '\\' in file or file.startswith('.'):
                problems.append(f'{where}.exports：文件名 {file!r} 不能包含路径')
        if 'decision' in stage:
            if stage['decision'] not in decisions:
                problems.append(f'{where} 引用的口径 {stage["decision"]!r} 未在 decisions 中声明')

    tools = spec.setdefault('tools', {})
    if not isinstance(tools, dict):
        problems.append('tools 应为对象：工具名 → 参数数组或 {argv, label}')
        tools = spec['tools'] = {}
    for name, tool in list(tools.items()):
        if isinstance(tool, list):
            tool = dict(argv=tool)
        if not isinstance(tool, dict) or not isinstance(tool.get('argv'), list) or not all(isinstance(a, str) for a in tool['argv']):
            problems.append(f'tools.{name} 应为字符串参数数组，或含 argv 的对象')
            continue
        tools[name] = dict(argv=tool['argv'], label=tool.get('label', name))

    report = spec.get('report')
    if report is not None:
        if not isinstance(report, dict) or not isinstance(report.get('builder'), str):
            problems.append('report 应为对象：{"builder": "report.py"}')
        elif base is not None and not (Path(base) / report['builder']).is_file():
            problems.append(f'report.builder 指向的文件不存在：{report["builder"]}')

    if problems:
        raise StudyError(path, problems)
    return spec


def load(path):
    path = Path(path)
    try:
        spec = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise StudyError(path, [f'不是合法 JSON：{exc}']) from None
    return normalize(spec, base=path.parent, path=path)

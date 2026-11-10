"""Execute a normalized study specification on local CSV sources with SQLite.

The engine only executes and records: it fills the stage entries of the run record and
emits events. Display, prompting and presentation happen in callbacks supplied by the CLI.
"""
import csv
import gzip
import sqlite3
import time

from .record import DecisionRequired, sha256
from .study import ident

EXAMPLES = 5


class CheckFailed(ValueError):
    def __init__(self, result):
        self.result = result
        example = f'，例如 {result["examples"][0]}' if result['examples'] else ''
        super().__init__(f'{result["name"]}：{result["violations"]:,} 行违规{example}')


def load_sources(db, spec, raw, run, emit):
    for table, source in spec['sources'].items():
        path = raw / source['file']
        emit('source.load', path.name, table=table)
        columns = source['columns']
        with path.open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream)
            missing = set(columns) - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f'{table}：{path.name} 缺少字段 {", ".join(sorted(missing))}')
            db.execute(f'CREATE TABLE {ident(table)} ({",".join(map(ident, columns))})')
            markers = ','.join('?' for _ in columns)
            db.executemany(f'INSERT INTO {ident(table)} VALUES ({markers})',
                           (tuple(row[c] or None for c in columns) for row in reader))
        rows = db.execute(f'SELECT count(*) FROM {ident(table)}').fetchone()[0]
        run['sources'][table] = dict(file=path.name, sha256=sha256(path), rows=rows, columns=columns)
        emit('source.loaded', f'{table} · {rows:,} 行', table=table, rows=rows)


def snapshot(db):
    """Row counts and columns of every table, used to report what a stage changed."""
    tables = {}
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        cursor = db.execute(f'SELECT * FROM "{name}" LIMIT 0')
        tables[name] = dict(rows=db.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0],
                            columns=[c[0] for c in cursor.description])
    return tables


def table_changes(before, after):
    changes = []
    for name, info in after.items():
        prev = before.get(name)
        if prev is None:
            changes.append(dict(name=name, change='created', **info))
        elif prev != info:
            changes.append(dict(name=name, change='modified', rows_before=prev['rows'], **info))
    for name in sorted(set(before) - set(after)):
        changes.append(dict(name=name, change='dropped', rows_before=before[name]['rows']))
    return changes


def run_check(db, check):
    sql = check['sql'].strip().rstrip(';')
    cursor = db.execute(sql)
    examples = [list(row) for row in cursor.fetchmany(EXAMPLES)]
    columns = [c[0] for c in cursor.description or ()]
    violations = 0
    if examples:
        try:
            violations = db.execute(f'SELECT count(*) FROM ({sql})').fetchone()[0]
        except sqlite3.Error:
            violations = None
    return dict(name=check['name'], severity=check['severity'], passed=not examples,
                violations=violations, columns=columns, examples=examples)


def export(db, query, path):
    cursor = db.execute(query)
    columns = [c[0] for c in cursor.description]
    opener = gzip.open if path.name.endswith('.gz') else open
    rows = 0
    with opener(path, 'wt', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        for row in cursor:
            writer.writerow(row)
            rows += 1
    return dict(file=path.name, rows=rows, columns=columns)


def try_plans(db, stage, record, emit, checkpoint):
    plans = stage['candidates']
    for plan in plans:
        attempt = dict(plan=plan['name'], outcome=None, reason=None, checks=[], duration_s=None)
        record['attempts'].append(attempt)
        emit('plan.start', plan['name'], plan=plan['name'], candidates=len(plans))
        started = time.perf_counter()
        db.execute('SAVEPOINT candidate')
        try:
            for sql in plan['sql']:
                emit('sql', sql)
                db.execute(sql)
            for check in stage['checks']:
                emit('check.start', check['name'])
                result = run_check(db, check)
                attempt['checks'].append(result)
                if result['passed']:
                    emit('check.pass', check['name'])
                elif check['severity'] == 'warn':
                    emit('check.warn', f'{check["name"]} · {result["violations"]:,} 行', **result)
                else:
                    emit('check.fail', f'{check["name"]} · {result["violations"]:,} 行', **result)
                    raise CheckFailed(result)
        except (ValueError, sqlite3.Error) as exc:
            if checkpoint:
                checkpoint(db, stage, 'rejected', exc)
            db.execute('ROLLBACK TO candidate')
            db.execute('RELEASE candidate')
            attempt.update(outcome='rejected', reason=str(exc), duration_s=round(time.perf_counter() - started, 3))
            emit('plan.rollback', f'{plan["name"]} · {exc}', plan=plan['name'])
            if plan is plans[-1]:
                raise
        else:
            db.execute('RELEASE candidate')
            attempt.update(outcome='accepted', duration_s=round(time.perf_counter() - started, 3))
            emit('plan.accept', plan['name'], plan=plan['name'])
            return


def apply_decision(db, spec, stage, record, emit, choose, out):
    name = stage['decision']
    decision = spec['decisions'][name]
    if choose:
        decision['value'] = choose(name, decision, out)
    value = decision['value']
    record['decision'] = dict(name=name, value=value, source=decision.get('source', 'default'))
    if value not in decision['options']:
        raise DecisionRequired(f'待研究者确定口径「{name}」；可选 {", ".join(decision["options"])}，证据见本次输出')
    emit('decision.made', f'{name} = {value}', name=name, value=value, source=record['decision']['source'])
    db.execute('CREATE TABLE decision(value TEXT)')
    db.execute('INSERT INTO decision VALUES (?)', (value,))


def run(spec, raw, out, run_record, emit, choose=None, checkpoint=None, on_stage_end=None):
    """Run every stage, filling run_record['sources'] and run_record['stages'] in place.

    Raises on the first stage that cannot complete; the failing stage is marked
    'failed' (or 'needs_decision') and later stages stay 'pending'.
    """
    db = sqlite3.connect(':memory:')
    try:
        load_sources(db, spec, raw, run_record, emit)
        for stage, record in zip(spec['stages'], run_record['stages']):
            started = time.perf_counter()
            record['status'] = 'running'
            emit('stage.start', stage['name'])
            before = snapshot(db)
            try:
                try_plans(db, stage, record, emit, checkpoint)
                for name, query in stage['exports'].items():
                    emit('export', name)
                    record['exports'].append(export(db, query, out / name))
                if checkpoint:
                    checkpoint(db, stage, 'done')
                if 'decision' in stage:
                    apply_decision(db, spec, stage, record, emit, choose, out)
            except DecisionRequired:
                record['status'] = 'needs_decision'
                raise
            except BaseException:
                record['status'] = 'failed'
                raise
            finally:
                record['tables'] = table_changes(before, snapshot(db))
                record['duration_s'] = round(time.perf_counter() - started, 3)
                if on_stage_end:
                    on_stage_end()
            record['status'] = 'passed'
            emit('stage.end', stage['name'], tables=len(record['tables']), exports=len(record['exports']))
            if on_stage_end:
                on_stage_end()
    finally:
        db.close()

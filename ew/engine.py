"""Execute a normalized study specification with DuckDB.

The engine only executes and records: it fills the stage entries of the run record and
emits events. Display, prompting and presentation happen in callbacks supplied by the CLI.
Each candidate plan runs in its own transaction and is rolled back if any SQL or
error-severity check fails. The database is kept as OUT/run.duckdb for later queries.
"""
import time

import duckdb

from . import io
from .record import DecisionRequired, sha256

EXAMPLES = 5
DATABASE = 'run.duckdb'


class CheckFailed(ValueError):
    def __init__(self, result):
        self.result = result
        example = f'，例如 {result["examples"][0]}' if result['examples'] else ''
        super().__init__(f'{result["name"]}：{result["violations"]:,} 行违规{example}')


def connect(path, read_only=False):
    return duckdb.connect(str(path), read_only=read_only)


def load_sources(db, spec, raw, run, emit):
    for table, source in spec['sources'].items():
        path = raw / source['file']
        emit('source.load', path.name, table=table)
        info = io.load(db, table, path, source)
        run['sources'][table] = dict(file=path.name, sha256=sha256(path), **info)
        emit('source.loaded', f'{table} · {info["rows"]:,} 行', table=table, rows=info['rows'])


def snapshot(db):
    """Row counts and columns of every table, used to report what a stage changed."""
    tables = {}
    names = [r[0] for r in db.execute("SELECT table_name FROM duckdb_tables() WHERE schema_name = 'main' ORDER BY table_name").fetchall()]
    for name in names:
        columns = [c[0] for c in db.execute(f'SELECT * FROM {io.ident(name)} LIMIT 0').description]
        tables[name] = dict(rows=db.execute(f'SELECT count(*) FROM {io.ident(name)}').fetchone()[0], columns=columns)
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


def plain(value):
    return value if value is None or isinstance(value, (int, float, str, bool)) else str(value)


def run_check(db, check):
    sql = check['sql'].strip().rstrip(';')
    cursor = db.execute(sql)
    columns = [c[0] for c in cursor.description or ()]
    examples = [[plain(v) for v in row] for row in cursor.fetchmany(EXAMPLES)]
    violations = db.execute(f'SELECT count(*) FROM ({sql})').fetchone()[0] if examples else 0
    return dict(name=check['name'], severity=check['severity'], passed=not examples,
                violations=violations, columns=columns, examples=examples)


def try_plans(db, stage, record, emit, checkpoint):
    plans = stage['candidates']
    for plan in plans:
        attempt = dict(plan=plan['name'], outcome=None, reason=None, checks=[], duration_s=None)
        record['attempts'].append(attempt)
        emit('plan.start', plan['name'], plan=plan['name'], candidates=len(plans))
        started = time.perf_counter()
        db.execute('BEGIN TRANSACTION')
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
        except (ValueError, duckdb.Error) as exc:
            if checkpoint and isinstance(exc, CheckFailed):
                checkpoint(db, stage, 'rejected', exc)
            db.execute('ROLLBACK')
            attempt.update(outcome='rejected', reason=str(exc).strip(), duration_s=round(time.perf_counter() - started, 3))
            emit('plan.rollback', f'{plan["name"]} · {attempt["reason"]}', plan=plan['name'])
            if plan is plans[-1]:
                raise
        except BaseException:
            db.execute('ROLLBACK')
            raise
        else:
            db.execute('COMMIT')
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
    db.execute('CREATE TABLE IF NOT EXISTS decisions(name VARCHAR PRIMARY KEY, value VARCHAR)')
    db.execute('INSERT OR REPLACE INTO decisions VALUES (?, ?)', [name, value])
    db.execute('CREATE OR REPLACE TABLE decision AS SELECT ?::VARCHAR AS value', [value])


def run(spec, raw, out, run_record, emit, choose=None, checkpoint=None, on_stage_end=None):
    """Run every stage, filling run_record['sources'] and run_record['stages'] in place.

    Raises on the first stage that cannot complete; the failing stage is marked
    'failed' (or 'needs_decision') and later stages stay 'pending'.
    """
    db = connect(out / DATABASE)
    run_record['database'] = DATABASE
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
                    record['exports'].append(io.export(db, query, out / name))
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

"""Run a trusted local study specification on CSV inputs, with SQLite and Python 3."""
import argparse
import csv
import gzip
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path


def ident(name):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', name):
        raise ValueError(f"Invalid SQL identifier {name!r}")
    return '"' + name + '"'


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def load_inputs(db, spec, raw, log, emit):
    for table, source in spec['sources'].items():
        path = raw / source['file']
        emit('读取', path.name)
        with path.open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream)
            columns = source['columns']
            if set(columns) - set(reader.fieldnames or []):
                raise ValueError(f'{table}: missing required columns')
            db.execute(f'CREATE TABLE {ident(table)} ({",".join(map(ident, columns))})')
            markers = ','.join('?' for _ in columns)
            db.executemany(f'INSERT INTO {ident(table)} VALUES ({markers})',
                           (tuple(row[c] or None for c in columns) for row in reader))
        log['sources'][table] = dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                     rows=db.execute(f'SELECT count(*) FROM {ident(table)}').fetchone()[0])
        emit('已读取', f"{table} · {log['sources'][table]['rows']:,} 行")


def run(args, emit=lambda kind, message: None, choose=None):
    spec = json.loads(args.study.read_text())
    out = args.out
    out.mkdir(parents=True, exist_ok=False)
    log = dict(status='running', study_sha256=hashlib.sha256(args.study.read_bytes()).hexdigest(),
               sources={}, checks=[], attempts=[], completed=[], decisions=spec.get('decisions', {}))
    db = sqlite3.connect(':memory:')
    try:
        load_inputs(db, spec, args.raw, log, emit)
        for stage in spec['stages']:
            log['current'] = stage['name']
            emit('阶段', stage['name'])
            plans = stage.get('candidates') or [{'name': 'main', 'sql': stage.get('sql', [])}]
            for plan in plans:
                emit('执行方案', plan['name'])
                db.execute('SAVEPOINT candidate')
                checks = []
                try:
                    for sql in plan['sql']:
                        emit('SQLite', sql)
                        db.execute(sql)
                    for name, query in stage.get('checks', {}).items():
                        emit('核验', name)
                        invalid = db.execute(query).fetchmany(5)
                        checks.append(dict(name=name, passed=not invalid, examples=invalid))
                        if invalid:
                            raise ValueError(f'{name}: {invalid}')
                        emit('通过', name)
                except (ValueError, sqlite3.Error) as exc:
                    db.execute('ROLLBACK TO candidate')
                    db.execute('RELEASE candidate')
                    emit('已回滚', f"{plan['name']} · {exc}")
                    log['attempts'].append(dict(stage=stage['name'], plan=plan['name'], outcome='rejected', reason=str(exc), checks=checks))
                    if plan is plans[-1]:
                        log['checks'].extend(checks)
                        raise
                else:
                    db.execute('RELEASE candidate')
                    log['attempts'].append(dict(stage=stage['name'], plan=plan['name'], outcome='accepted'))
                    log['checks'].extend(checks)
                    break
            for name, query in stage.get('exports', {}).items():
                emit('生成', name)
                cursor = db.execute(query)
                opener = gzip.open if name.endswith('.gz') else open
                with opener(out/name, 'wt', encoding='utf-8', newline='') as stream:
                    writer = csv.writer(stream)
                    writer.writerow([col[0] for col in cursor.description])
                    writer.writerows(cursor)
            if 'decision' in stage:
                name = stage['decision']
                value = spec['decisions'][name]['value']
                decision = spec['decisions'][name]
                if choose:
                    value = choose(name, decision, out)
                    decision['value'] = value
                emit('采用口径', f'{name} = {value}')
                if value not in spec['decisions'][name]['options']:
                    raise ValueError(f'待研究者确定 {name}；见本次输出的口径比较表')
                db.execute('CREATE TABLE decision(value TEXT)')
                db.execute('INSERT INTO decision VALUES (?)', (value,))
            log['completed'].append(stage['name'])
        log['status'] = 'passed'
    except Exception as error:
        log.update(status='stopped', reason=str(error))
        raise
    finally:
        dump(out/'run.json', log)
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['study', 'raw', 'out']:
        parser.add_argument('--'+name, required=True, type=Path)
    run(parser.parse_args())

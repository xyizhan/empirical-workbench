"""Local web workbench: `ew serve` serves the built frontend (ew/web) and a small JSON API.

Binds to 127.0.0.1 only. Runs are started as `ew run --batch` subprocesses; the browser
follows them by polling run.json / events.jsonl, which the engine updates as it goes.
"""
import importlib.resources
import json
import mimetypes
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

import duckdb

from . import __version__, engine, record, report, study as studies

PREVIEW_LIMIT = 200
QUERY_LIMIT = 1000


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def child(root, name):
    """Resolve a single path component under root, rejecting traversal."""
    if not name or '/' in name or '\\' in name or name in ('.', '..') or name.startswith('.'):
        raise ApiError(404, '路径无效')
    path = (root / name).resolve()
    if path.parent != root.resolve():
        raise ApiError(404, '路径无效')
    return path


def rows_json(columns, rows):
    return dict(columns=columns, rows=[[v if v is None or isinstance(v, (int, float, str, bool)) else str(v) for v in r] for r in rows])


class Workbench:
    def __init__(self, runs, studies_root):
        self.runs = Path(runs).resolve()
        self.studies = Path(studies_root).resolve()
        self.runs.mkdir(parents=True, exist_ok=True)
        self.jobs = {}
        self.lock = threading.Lock()

    # ----- studies -----
    def study_id(self, run):
        directory = Path(run['study']['dir']).resolve()
        return directory.name if directory.parent == self.studies else None

    def list_studies(self):
        items = []
        for path in sorted(self.studies.glob('*/study.json')):
            item = dict(id=path.parent.name)
            try:
                spec = studies.load(path)
                item.update(title=spec.get('title') or spec.get('guide', {}).get('title') or path.parent.name,
                            question=spec.get('question', ''), stages=[s['name'] for s in spec['stages']],
                            decisions={k: dict(options=v['options'], labels=v.get('labels', {}), value=v['value'],
                                               basis=v.get('default_basis', '')) for k, v in spec['decisions'].items()})
            except studies.StudyError as exc:
                item.update(title=path.parent.name, error=str(exc))
            items.append(item)
        return items

    # ----- runs -----
    def load_run(self, run_id):
        out = child(self.runs, run_id)
        if not (out / 'run.json').is_file():
            job = self.jobs.get(run_id)
            if job and job['proc'].poll() is None:
                return out, None
            raise ApiError(404, '找不到这次运行')
        try:
            run = record.load(out)
        except ValueError as exc:
            raise ApiError(409, str(exc))
        job = self.jobs.get(run_id)
        if run['status'] == record.RUNNING and job and job['proc'].poll() is not None:
            run.update(status=record.FAILED, reason=job['stderr'].read_text(encoding='utf-8', errors='replace').strip() or '运行进程意外退出')
        return out, run

    def list_runs(self):
        items = []
        for path in self.runs.iterdir():
            if not path.is_dir() or path.name.startswith('.'):
                continue
            try:
                _, run = self.load_run(path.name)
            except ApiError:
                continue
            if run is None:
                items.append(dict(id=path.name, status=record.RUNNING, title=path.name, started_at=None))
                continue
            items.append(dict(id=path.name, status=run['status'], title=run['study']['title'], study_id=self.study_id(run),
                              started_at=run['started_at'], duration_s=run['duration_s'],
                              decisions={k: v['value'] for k, v in run['decisions'].items()}))
        return sorted(items, key=lambda r: r['started_at'] or '9999', reverse=True)

    def run_detail(self, run_id):
        _, run = self.load_run(run_id)
        if run is None:
            return dict(id=run_id, run=None)
        return dict(id=run_id, run=run, study_id=self.study_id(run))

    def events(self, run_id, after):
        out = child(self.runs, run_id)
        path = out / 'events.jsonl'
        if not path.is_file():
            return []
        events = []
        with path.open(encoding='utf-8') as stream:
            for line in stream:
                if not line.endswith('\n'):
                    break
                event = json.loads(line)
                if event['seq'] > after:
                    events.append(event)
        return events

    def start(self, body):
        study_id = body.get('study')
        study_path = child(self.studies, str(study_id)) / 'study.json'
        if not study_path.is_file():
            raise ApiError(400, f'找不到研究 {study_id}')
        try:
            spec = studies.load(study_path)
        except studies.StudyError as exc:
            raise ApiError(400, str(exc))
        raw = Path(str(body.get('raw') or '')).expanduser()
        if not raw.is_absolute():
            raw = (Path.cwd() / raw).resolve()
        if not raw.is_dir():
            raise ApiError(400, f'原始数据目录不存在：{raw}')
        missing = [s['file'] for s in spec['sources'].values() if not (raw / s['file']).is_file()]
        if missing:
            raise ApiError(400, f'原始数据目录缺少文件：{", ".join(missing)}')
        argv = [sys.executable, '-m', 'ew.cli', 'run', str(study_path), '--raw', str(raw)]
        for name, value in (body.get('decisions') or {}).items():
            if name not in spec['decisions']:
                raise ApiError(400, f'未知口径 {name}')
            if value and value not in spec['decisions'][name]['options']:
                raise ApiError(400, f'口径 {name} 不能取 {value}')
            argv += ['--decision', f'{name}={value or ""}']
        with self.lock:
            stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
            run_id, n = f'{study_id}-{stamp}', 1
            while (self.runs / run_id).exists() or run_id in self.jobs:
                n += 1
                run_id = f'{study_id}-{stamp}-{n}'
            logs = self.runs / '.ew-serve'
            logs.mkdir(exist_ok=True)
            stderr = logs / f'{run_id}.log'
            proc = subprocess.Popen(argv + ['--out', str(self.runs / run_id), '--batch'], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=stderr.open('w'))
            self.jobs[run_id] = dict(proc=proc, stderr=stderr)
        for _ in range(40):  # surface start-up errors (before run.json exists) directly
            if (self.runs / run_id / 'run.json').is_file() or proc.poll() is not None:
                break
            time.sleep(0.05)
        if proc.poll() not in (None, 0) and not (self.runs / run_id / 'run.json').is_file():
            raise ApiError(400, stderr.read_text(encoding='utf-8', errors='replace').strip() or '运行无法启动')
        return dict(id=run_id)

    def preview(self, run_id, name, limit):
        out, run = self.load_run(run_id)
        path = child(out, name)
        if not path.is_file():
            raise ApiError(404, f'没有文件 {name}')
        db = duckdb.connect()
        try:
            cursor = db.execute('SELECT * FROM ' + ("read_csv(?, header=true, all_varchar=true)" if '.csv' in name else 'read_parquet(?)') + f' LIMIT {int(limit)}', [str(path)])
            return rows_json([c[0] for c in cursor.description], cursor.fetchall())
        finally:
            db.close()

    def query(self, run_id, body):
        out, run = self.load_run(run_id)
        if run is None or run['status'] == record.RUNNING:
            raise ApiError(409, '运行尚未结束，结束后才能查询工作数据库')
        if not run.get('database') or not (out / run['database']).is_file():
            raise ApiError(404, '这次运行没有保存工作数据库')
        limit = min(int(body.get('limit') or QUERY_LIMIT), QUERY_LIMIT)
        try:
            db = engine.connect(out / run['database'], read_only=True)
        except duckdb.Error as exc:
            raise ApiError(409, f'数据库暂不可读：{exc}')
        try:
            started = time.perf_counter()
            cursor = db.execute(str(body.get('sql') or ''))
            if cursor.description is None:
                return dict(columns=[], rows=[], truncated=False, duration_s=0)
            rows = cursor.fetchmany(limit + 1)
            result = rows_json([c[0] for c in cursor.description], rows[:limit])
            result.update(truncated=len(rows) > limit, duration_s=round(time.perf_counter() - started, 3))
            return result
        except duckdb.Error as exc:
            raise ApiError(400, str(exc).strip())
        finally:
            db.close()

    def make_report(self, run_id):
        out, run = self.load_run(run_id)
        if run is None or run['status'] != record.PASSED:
            raise ApiError(409, '只有全部核验通过的运行才能生成报告')
        try:
            if report.quarto():
                report.render(out, quiet=True)
            else:
                report.write_source(out)
        except (FileNotFoundError, ValueError, subprocess.CalledProcessError) as exc:
            raise ApiError(500, str(exc))
        return self.run_detail(run_id)


def make_handler(bench, web_root):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'ew-workbench'

        def log_message(self, fmt, *args):
            pass

        def send_json(self, value, status=200):
            data = json.dumps(value, ensure_ascii=False, default=str).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def send_file(self, path, download=False):
            data = path.read_bytes()
            ctype = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
            if ctype.startswith('text/') or ctype in ('application/javascript', 'application/json'):
                ctype += '; charset=utf-8'
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            if download:
                self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(path.name))
            self.end_headers()
            self.wfile.write(data)

        def handle_api(self, method):
            url = urlparse(self.path)
            parts = [unquote(p) for p in url.path.split('/')[2:] if p]
            query = {k: v[-1] for k, v in parse_qs(url.query).items()}
            body = {}
            if method == 'POST':
                origin = self.headers.get('Origin')
                if origin and urlparse(origin).netloc != self.headers.get('Host'):
                    raise ApiError(403, '拒绝跨站请求')
                if 'application/json' not in (self.headers.get('Content-Type') or ''):
                    raise ApiError(415, '需要 JSON 请求体')
                length = int(self.headers.get('Content-Length') or 0)
                body = json.loads(self.rfile.read(length) or b'{}')
            match (method, parts):
                case ('GET', ['meta']):
                    return dict(version=__version__, events=record.EVENTS,
                                runs=str(bench.runs), studies=str(bench.studies), cwd=str(Path.cwd()), quarto=bool(report.quarto()))
                case ('GET', ['studies']):
                    return bench.list_studies()
                case ('GET', ['runs']):
                    return bench.list_runs()
                case ('POST', ['runs']):
                    return bench.start(body)
                case ('GET', ['runs', run_id]):
                    return bench.run_detail(run_id)
                case ('GET', ['runs', run_id, 'events']):
                    return bench.events(run_id, int(query.get('after', 0)))
                case ('GET', ['runs', run_id, 'preview', name]):
                    return bench.preview(run_id, name, min(int(query.get('limit', PREVIEW_LIMIT)), 5000))
                case ('GET', ['runs', run_id, 'files', name]):
                    out, _ = bench.load_run(run_id)
                    path = child(out, name)
                    if not path.is_file():
                        raise ApiError(404, f'没有文件 {name}')
                    self.send_file(path, download=query.get('download') == '1')
                    return None
                case ('POST', ['runs', run_id, 'query']):
                    return bench.query(run_id, body)
                case ('POST', ['runs', run_id, 'report']):
                    return bench.make_report(run_id)
            raise ApiError(404, '没有这个接口')

        def dispatch(self, method):
            if self.path.startswith('/api/'):
                try:
                    result = self.handle_api(method)
                    if result is not None:
                        self.send_json(result)
                except ApiError as exc:
                    self.send_json(dict(error=str(exc)), exc.status)
                except (ValueError, json.JSONDecodeError) as exc:
                    self.send_json(dict(error=f'请求无效：{exc}'), 400)
                except Exception as exc:  # keep the server alive; report to the page
                    self.send_json(dict(error=f'{type(exc).__name__}: {exc}'), 500)
                return
            if method != 'GET':
                self.send_json(dict(error='不支持'), 405)
                return
            relative = urlparse(self.path).path.lstrip('/')
            target = (web_root / relative).resolve() if relative else None
            if target and target.is_file() and web_root.resolve() in target.parents:
                self.send_file(target)
            elif (web_root / 'index.html').is_file():
                self.send_file(web_root / 'index.html')
            else:
                self.send_json(dict(error='前端尚未构建：在 frontend/ 运行 npm install && npm run build'), 500)

        def do_GET(self):
            self.dispatch('GET')

        def do_POST(self):
            self.dispatch('POST')

    return Handler


def serve(runs, studies_root, port=8765, open_browser=False):
    bench = Workbench(runs, studies_root)
    web_root = Path(str(importlib.resources.files('ew').joinpath('web')))
    httpd = ThreadingHTTPServer(('127.0.0.1', port), make_handler(bench, web_root))
    url = f'http://127.0.0.1:{httpd.server_address[1]}/'
    print(f'Empirical Workbench 工作台：{url}\n运行目录 {bench.runs}　研究目录 {bench.studies}\n按 Ctrl+C 退出', flush=True)
    if open_browser:
        import webbrowser
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()

"""Command line for Empirical Workbench."""
import argparse
import csv
import importlib.resources
import json
import subprocess
import sys
import time
import webbrowser
from itertools import islice
from pathlib import Path

import duckdb

from . import __version__, engine, io, record, report, study as studies
from . import project
from .profile import profile_table
from .record import EVENTS, DecisionRequired, Interrupted, Recorder
from .terminal import show_run

PREVIEW_ROWS = 50


def dashboard(out):
    """Write the offline single-file viewer index.html for a run directory."""
    run = json.loads((out / 'run.json').read_text(encoding='utf-8'))
    tables = {}
    for stage in run['stages']:
        for item in stage['exports']:
            path = out / item['file']
            if path.suffix == '.csv' and path.is_file():
                with path.open(newline='', encoding='utf-8') as stream:
                    tables[item['file']] = list(islice(csv.reader(stream), PREVIEW_ROWS + 1))
    payload = json.dumps(dict(run=run, tables=tables, labels=EVENTS), ensure_ascii=False, default=str).replace('<', '\\u003c')
    template = importlib.resources.files('ew').joinpath('console.html').read_text(encoding='utf-8')
    (out / 'index.html').write_text(template.replace('__PAYLOAD__', payload), encoding='utf-8')


def prompt_decision(name, decision, out):
    print(f'\n◆ 需要研究者选择 · {name}', flush=True)
    if decision.get('evidence') and (out / decision['evidence']).is_file():
        with (out / decision['evidence']).open(newline='', encoding='utf-8') as stream:
            row = next(csv.DictReader(stream), {})
        for field, label in decision.get('fields', {}).items():
            print(f'  {label}  {row.get(field, "")}')
    options = decision['options']
    for index, value in enumerate(options, 1):
        print(f"  [{index}] {decision.get('labels', {}).get(value, value)}  ({value})")
    while True:
        try:
            answer = input('选择编号或口径名称 › ').strip()
        except (EOFError, KeyboardInterrupt):
            raise Interrupted('研究者未选择口径，运行已停止') from None
        for index, value in enumerate(options, 1):
            if answer in (str(index), value):
                decision['source'] = 'interactive'
                return value
        print('请从上列选项中选择。')


def printer(event):
    message = event['message']
    if event['kind'] == 'sql' and len(message) > 108:
        message = message[:105] + '…'
    print(f'[{EVENTS[event["kind"]]}] {message}', flush=True)


def run_tools(spec, study_dir, raw, out, run, emit, save):
    ctx = dict(python=sys.executable, study=str(study_dir), raw=str(raw.resolve()), out=str(out))
    for name, tool in spec['tools'].items():
        argv = [part.format_map(ctx) for part in tool['argv']]
        entry = dict(name=name, label=tool['label'], argv=argv, returncode=None, log=f'{name}.log', duration_s=None)
        run['tools'].append(entry)
        save()
        emit('tool.start', ' '.join(argv), name=name, label=tool['label'])
        started = time.perf_counter()
        result = subprocess.run(argv, capture_output=True, text=True, timeout=300)
        output = result.stdout + result.stderr
        (out / entry['log']).write_text(output, encoding='utf-8')
        entry.update(returncode=result.returncode, duration_s=round(time.perf_counter() - started, 3))
        emit('tool.end', output.strip() or f'exit {result.returncode}', name=name, returncode=result.returncode)
        if result.returncode:
            raise RuntimeError(f'工具 {name} 失败（exit {result.returncode}），见 {entry["log"]}')


def cmd_run(args, parser):
    raw = args.raw
    if project.is_project(args.study):
        root = args.study.resolve()
        try:
            if args.topic:
                spec, study_path = project.topic_spec(root, args.topic, args.base)
            else:
                spec, study_path = project.base_spec(root)
        except project.ProjectError as exc:
            parser.error(str(exc))
        raw = raw or project.raw_dir(root)
        args.out = args.out or project.new_out(root, args.topic or 'base')
    else:
        if args.topic or args.base:
            parser.error('--topic / --base 只用于研究项目目录')
        if not raw or not args.out:
            parser.error('运行单个研究配置需要 --raw 和 --out')
        study_path = args.study.resolve()
        spec = studies.load(study_path)
    explicit = set()
    for setting in args.decision:
        key, sep, value = setting.partition('=')
        if not sep or key not in spec['decisions']:
            parser.error(f'--decision 需要 KEY=VALUE，KEY 为研究配置中的口径：{", ".join(spec["decisions"]) or "（无）"}')
        if value and value not in spec['decisions'][key]['options']:
            parser.error(f'口径 {key} 的可选值为 {", ".join(spec["decisions"][key]["options"])}')
        explicit.add(key)
        spec['decisions'][key].update(value=value or None, source='command-line')
    classroom = args.cmd == 'demo'
    if classroom and not (sys.stdin.isatty() and sys.stdout.isatty()):
        parser.error('ew demo 需要交互终端；自动化请使用 ew run --batch')
    out = args.out.resolve()
    try:
        out.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        parser.error(f'输出目录已存在：{out}。每次运行请使用新目录')
    record.save_json(out / 'study.json', spec)

    interactive = sys.stdin.isatty() if args.interactive is None else args.interactive
    run = record.new_run(study_path, spec, Path(raw).resolve())
    recorder = Recorder(out, run)
    presenter = None
    if classroom:
        from .demo import Classroom
        presenter = Classroom(spec, recorder.emit)
        recorder.listeners.append(presenter.event)
        interactive = True
    elif interactive:
        recorder.listeners.append(printer)

    def choose(name, decision, directory):
        if interactive and name not in explicit:
            return prompt_decision(name, decision, directory)
        return decision['value']

    recorder.save()
    status, reason = record.PASSED, None
    try:
        if presenter:
            presenter.intro()
        recorder.emit('run.start', spec.get('question') or run['study']['title'])
        engine.run(spec, Path(raw), out, run, recorder.emit, choose,
                   presenter.checkpoint if presenter else None, recorder.save)
        recorder.save()
        run_tools(spec, study_path.parent, Path(raw), out, run, recorder.emit, recorder.save)
    except DecisionRequired as exc:
        status, reason = record.NEEDS_DECISION, str(exc)
    except (Interrupted, KeyboardInterrupt) as exc:
        status, reason = record.INTERRUPTED, str(exc) or '运行被中断'
    except Exception as exc:
        status, reason = record.FAILED, str(exc)
    recorder.finish(status, reason)
    dashboard(out)
    print(f'运行记录：{out}（ew view 查看）')
    if status != record.PASSED:
        sys.exit(reason)
    if args.report:
        try:
            report.render(out, quiet=classroom)
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            sys.exit(f'报告未生成：{exc}')
        dashboard(out)
    if presenter:
        presenter.finish(out)


def cmd_inspect(args):
    paths = [args.raw] if args.raw.is_file() else sorted(p for p in args.raw.iterdir()
                                                         if p.suffix.lower() in io.TEXT + io.PANDAS + ('.parquet',) and not p.name.startswith('.'))
    db = engine.connect(':memory:')
    profiles = {}
    for index, path in enumerate(paths):
        table = f'source_{index}'
        try:
            info = io.load(db, table, path, {})
        except Exception as exc:
            profiles[path.name] = dict(error=str(exc))
            continue
        profiles[path.name] = dict(encoding=info['encoding'], **profile_table(db, table))
    if args.json:
        print(json.dumps(profiles, ensure_ascii=False, indent=2, default=str))
        return
    from rich.console import Console
    from rich.table import Table
    console = Console()
    for name, prof in profiles.items():
        if 'error' in prof:
            console.print(f'[red]{name}：{prof["error"]}[/red]')
            continue
        table = Table(title=f'{name}　{prof["rows"]:,} 行' + (f'　编码 {prof["encoding"]}' if prof['encoding'] not in (None, 'utf-8') else ''),
                      title_justify='left', header_style='bold cyan')
        for head in ('字段', '类型', '缺失', '不同值≈', '最小', '最大', '提示'):
            table.add_column(head, overflow='fold')
        for c in prof['columns']:
            table.add_row(c['name'], c['type'], f'{c["missing"]:,}（{c["missing_share"]:.1%}）' if c['missing'] else '0',
                          f'{c["distinct"]:,}', str(c['min'])[:24], str(c['max'])[:24], '；'.join(c['hints']))
        console.print(table)


def cmd_query(args):
    out = args.out.resolve()
    run = record.load(out)
    if not run.get('database') or not (out / run['database']).is_file():
        raise ValueError(f'{out} 没有保存工作数据库')
    db = engine.connect(out / run['database'], read_only=True)
    try:
        cursor = db.execute(args.sql)
        columns = [c[0] for c in cursor.description or ()]
        rows = cursor.fetchmany(args.limit) if args.limit else cursor.fetchall()
    finally:
        db.close()
    if args.format == 'json':
        print(json.dumps([dict(zip(columns, r)) for r in rows], ensure_ascii=False, indent=2, default=str))
    elif args.format == 'csv':
        writer = csv.writer(sys.stdout)
        writer.writerow(columns)
        writer.writerows(rows)
    else:
        from rich.console import Console
        from rich.table import Table
        table = Table(header_style='bold cyan')
        for column in columns:
            table.add_column(column, overflow='fold')
        for row in rows:
            table.add_row(*('缺失' if v is None else str(v) for v in row))
        Console().print(table)
        print(f'{len(rows):,} 行' + ('（已截断，--limit 0 显示全部）' if args.limit and len(rows) == args.limit else ''))


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ew', description='Empirical Workbench：可核验的实证数据处理工作台')
    parser.add_argument('--version', action='version', version=f'ew {__version__}')
    cmds = parser.add_subparsers(dest='cmd', required=True)
    inspect = cmds.add_parser('inspect', help='概览原始文件：类型、缺失、候选主键与异常提示')
    inspect.add_argument('raw', type=Path, help='数据目录或单个文件')
    inspect.add_argument('--json', action='store_true', help='输出 JSON，便于 Agent 读取')
    query = cmds.add_parser('query', help='在一次运行的工作数据库上执行只读 SQL')
    query.add_argument('out', type=Path)
    query.add_argument('sql')
    query.add_argument('--format', choices=['table', 'csv', 'json'], default='table')
    query.add_argument('--limit', type=int, default=50, help='最多显示行数，0 为全部')
    validate = cmds.add_parser('validate', help='检查研究配置，不读取数据')
    validate.add_argument('study', type=Path)
    run = cmds.add_parser('run', aliases=['demo'], help='执行研究（demo 为课堂投影模式）')
    run.add_argument('study', type=Path, help='研究配置 study.json，或研究项目目录')
    run.add_argument('--raw', type=Path, help='原始数据目录（研究项目自动使用项目登记的目录）')
    run.add_argument('--out', type=Path, help='新的输出目录（研究项目自动放在 runs/ 下）')
    run.add_argument('--topic', help='研究项目中要运行的选题；省略则运行数据底座')
    run.add_argument('--base', type=Path, help='选题使用的底座运行目录；默认最近一次通过的底座')
    run.add_argument('--decision', action='append', default=[], metavar='KEY=VALUE')
    mode = run.add_mutually_exclusive_group()
    mode.add_argument('--interactive', dest='interactive', action='store_true')
    mode.add_argument('--batch', dest='interactive', action='store_false')
    run.set_defaults(interactive=None)
    run.add_argument('--report', action='store_true', help='核验后生成报告（需要 Quarto）')
    chat = cmds.add_parser('chat', help='与研究助理一起理解数据、确定选题并完成处理')
    chat.add_argument('project', type=Path, help='研究项目目录（不存在时用 --raw 新建）')
    chat.add_argument('--raw', type=Path, help='新建项目时的原始数据目录')
    chat.add_argument('--name', help='新建项目的名称（默认取目录名）')
    chat.add_argument('--new', action='store_true', help='忽略已保存的对话，重新开始')
    serve = cmds.add_parser('serve', help='启动本地网页工作台')
    serve.add_argument('--runs', type=Path, default=Path('runs'), help='运行目录（默认 runs）')
    serve.add_argument('--studies', type=Path, default=Path('studies'), help='研究配置目录（默认 studies）')
    serve.add_argument('--port', type=int, default=8765)
    serve.add_argument('--open', action='store_true', help='启动后打开浏览器')
    view = cmds.add_parser('view', help='查看一次运行')
    view.add_argument('out', type=Path)
    view.add_argument('--web', action='store_true')
    rep = cmds.add_parser('report', help='为已通过的运行生成报告')
    rep.add_argument('out', type=Path)
    rep.add_argument('--source-only', action='store_true', help='只写出 report.qmd，不调用 Quarto')
    args = parser.parse_args(argv)

    try:
        if args.cmd == 'inspect':
            cmd_inspect(args)
        elif args.cmd == 'chat':
            from .agent import Chat
            from .llm import LLMError
            if not project.is_project(args.project):
                if not args.raw:
                    parser.error(f'{args.project} 还不是研究项目；新建请加 --raw 原始数据目录')
                project.create(args.project, args.raw, args.name)
                print(f'已新建研究项目：{args.project.resolve()}')
            try:
                Chat(args.project.resolve()).loop(fresh=args.new)
            except LLMError as exc:
                sys.exit(str(exc))
        elif args.cmd == 'serve':
            from .server import serve as start_server
            start_server(args.runs, args.studies, args.port, args.open)
        elif args.cmd == 'query':
            cmd_query(args)
        elif args.cmd == 'validate':
            spec = studies.load(args.study)
            print(f'✓ {args.study}：{len(spec["sources"])} 个来源，{len(spec["stages"])} 个阶段，'
                  f'{sum(len(s["checks"]) for s in spec["stages"])} 项核验，{len(spec["decisions"])} 个研究口径')
        elif args.cmd in ('run', 'demo'):
            cmd_run(args, parser)
        elif args.cmd == 'view':
            out = args.out.resolve()
            record.load(out)
            if args.web:
                dashboard(out)
                webbrowser.open((out / 'index.html').as_uri())
            else:
                show_run(out)
        elif args.cmd == 'report':
            out = args.out.resolve()
            path = report.write_source(out) if args.source_only else report.render(out)
            dashboard(out)
            print(path)
    except studies.StudyError as exc:
        sys.exit(str(exc))
    except (ValueError, FileNotFoundError, RuntimeError, duckdb.Error, subprocess.CalledProcessError) as exc:  # includes ProjectError
        sys.exit(f'ew {args.cmd}：{exc}')


if __name__ == '__main__':
    main()

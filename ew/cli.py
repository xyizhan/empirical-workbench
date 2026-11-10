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

from . import __version__, engine, record, report, study as studies
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
    run = record.new_run(study_path, spec, args.raw.resolve())
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
        engine.run(spec, args.raw, out, run, recorder.emit, choose,
                   presenter.checkpoint if presenter else None, recorder.save)
        recorder.save()
        run_tools(spec, study_path.parent, args.raw, out, run, recorder.emit, recorder.save)
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
    profile = {}
    for path in sorted(args.raw.glob('*.csv')):
        with path.open(newline='', encoding='utf-8-sig') as stream:
            reader = csv.DictReader(stream)
            fields = reader.fieldnames or []
            nulls = dict.fromkeys(fields, 0)
            count = 0
            for row in reader:
                count += 1
                for field in fields:
                    if not row[field]:
                        nulls[field] += 1
            profile[path.name] = dict(rows=count, missing=nulls)
    print(json.dumps(profile, ensure_ascii=False, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ew', description='Empirical Workbench：可核验的实证数据处理工作台')
    parser.add_argument('--version', action='version', version=f'ew {__version__}')
    cmds = parser.add_subparsers(dest='cmd', required=True)
    inspect = cmds.add_parser('inspect', help='概览目录中 CSV 的行数与缺失')
    inspect.add_argument('raw', type=Path)
    validate = cmds.add_parser('validate', help='检查研究配置，不读取数据')
    validate.add_argument('study', type=Path)
    run = cmds.add_parser('run', aliases=['demo'], help='执行研究（demo 为课堂投影模式）')
    run.add_argument('study', type=Path)
    run.add_argument('--raw', required=True, type=Path)
    run.add_argument('--out', required=True, type=Path)
    run.add_argument('--decision', action='append', default=[], metavar='KEY=VALUE')
    mode = run.add_mutually_exclusive_group()
    mode.add_argument('--interactive', dest='interactive', action='store_true')
    mode.add_argument('--batch', dest='interactive', action='store_false')
    run.set_defaults(interactive=None)
    run.add_argument('--report', action='store_true', help='核验后生成报告（需要 Quarto）')
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
    except (ValueError, FileNotFoundError, subprocess.CalledProcessError) as exc:
        sys.exit(f'ew {args.cmd}：{exc}')


if __name__ == '__main__':
    main()

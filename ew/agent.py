"""`ew chat`: a research agent that works with the researcher in the terminal.

The model (any OpenAI-compatible API, see ew/llm.py) drives the workbench only through
the tools below. Two rules are enforced in code, not left to the model: a topic card
becomes 'confirmed' only when the researcher confirms it at the terminal, and topic
stages (variable construction, exploration) can only be written for confirmed cards.
"""
import json
import subprocess
import sys
from pathlib import Path

from . import engine, io, project, record, study as studies
from .llm import Client, LLMError
from .profile import profile_table

MAX_TOOL_ROUNDS = 40
TOOL_OUTPUT_LIMIT = 14000

SYSTEM = """你是 Empirical Workbench 的研究数据助理，和一位经管领域的研究者在终端里合作。研究者拿到了一份不熟悉的数据，你要帮他看懂数据、做好与选题无关的处理，再一起确定选题，然后完成该选题的样本与变量构造和探索分析。

# 工作流（按顺序推进，研究者可以随时打断、换题或回到前面的阶段）

A. 理解数据并搭建「数据底座」（与选题无关，可以直接做）
  1. 用 inspect_data 看每个文件的字段、类型、缺失与提示；用 query(target="raw") 核对每张表的观察单位（一行代表什么）和主键是否唯一、表与表之间靠什么键关联、匹配率如何。
  2. 用 write_base 写底座：类型与编码修正、重复核对、按正确粒度合并（先汇总明细再连接，避免一对多膨胀）、对账守恒、质量标记。
  3. 用 run(target="base") 运行，读结果，有问题就修改再跑。
  底座的硬规则：只标记、不删除。不按选题筛样本，不缩尾，不插补，不构造研究变量；异常和缺失用标记列或质量表记录，留给选题决定。每个底座阶段都要写核验（返回违规行的 SQL）。
  边做边用两三句话告诉研究者你发现了什么（例如"订单表一行一单，商品表一单多行，所以先按订单汇总再合并"）。

B. 写数据档案并给出方向
  用 write_profile 写一份简短的 Markdown 数据档案：数据是什么（来源、时间范围、实体与粒度）、表之间的关系与匹配情况、主要质量问题及处理方式、可研究的方向 3–5 条（每条一两句：可以问什么问题、用到哪些字段、主要局限）。不要写得太长。然后简要转述给研究者，问他对哪个方向感兴趣，或者有自己的想法。

C. 和研究者讨论，确定选题
  不要替研究者决定选题。根据他的兴趣澄清：研究问题、分析单位、被解释变量、核心解释变量、样本范围、哪些口径需要他定。每轮最多问 1–3 个问题。想法清楚后用 propose_topic 提交选题卡，研究者会在终端确认或提出修改；只有他确认后才能进入 D。

D. 选题内的样本、变量与探索
  用 write_topic 写选题阶段：样本筛选（每一步保留多少样本要能看到）、变量构造、描述统计与分组对比（导出成 CSV）。存在合理的不同定义且会影响结果时，用 decisions 声明，value 设为 null，运行会在该处暂停并导出证据；你向研究者解释证据和差异，请他选择；只有他明确选定后，才用 run(target=选题, decisions={...}) 重跑（工具会再请他确认一次）。不要替研究者选口径，即使你有倾向，也只能作为建议。结论只描述相关关系，不做因果断言。

换题：研究者随时可以提出新的选题或并行多个选题，用新的 slug 走 C→D，底座不用重跑。如果新选题需要底座里没有的数据或合并，先回到 A 修改底座并重跑。

# 配置格式

底座 write_base(spec)：
{"sources": {"orders": {"file": "orders.csv", "columns": ["可选，省略读全部字段"], "types": {"字段": "VARCHAR"}}},
 "stages": [{"name": "1 识别粒度", "description": "一句话说明",
             "sql": ["create table ... as select ..."],
             "checks": {"订单主键唯一": "select order_id from orders group by 1 having count(*)>1",
                        "提醒类核验": {"sql": "select ...", "severity": "warn"}},
             "exports": {"匹配对账.csv": "select ..."}}]}
选题 write_topic(slug, stages, decisions)：stages 格式同上，可直接使用底座运行产生的所有表（含原始来源表）；
decisions 形如 {"延误定义": {"options": ["calendar", "clock"], "value": null, "labels": {"calendar": "按自然日"}, "evidence": "口径比较.csv", "fields": {"switched": "换组订单数"}}}，
某阶段用 "decision": "延误定义" 表示在该阶段结束时确定（带取值运行时，工具会先请研究者在终端确认该取值）；之后的 SQL 可读表 decision(value) 或 decisions(name, value)。
导出文件名用中文、带 .csv（大表可用 .parquet）。候选方案可写 "candidates": [{"name": "方案甲", "sql": [...]}, ...]（与 sql 二选一），失败自动回滚并尝试下一个。

# SQL 是 DuckDB 方言
字段按真实类型读入（时间戳是 TIMESTAMP，以 0 开头的代码是 VARCHAR）。GROUP BY 必须列出全部非聚合字段；布尔值可直接 sum；日期差用 date_diff('day', a, b)；需要稳定顺序的导出写 ORDER BY。

# 沟通
用中文，简洁，先结论后依据。所有数字都来自工具结果，不要编造。工具报错时读错误信息修正后重试，不要把内部配置 JSON 整段贴给研究者。"""

TOOLS = [
    ('project_state', '查看项目现状：原始文件、底座阶段与最近运行、数据档案摘要、各选题及其状态。', {}),
    ('inspect_data', '概览全部原始文件：行数、编码、每个字段的类型、缺失、不同值个数、范围和提示（候选主键、前导零代码等）。', {}),
    ('query', '执行只读 DuckDB SQL。target="raw" 查原始文件（表名与底座 sources 相同）；"base" 查最近一次底座运行的全部表；"topic:<slug>" 查该选题最近一次运行。',
     {'sql': {'type': 'string'}, 'target': {'type': 'string', 'default': 'raw'}, 'limit': {'type': 'integer', 'default': 30}}, ['sql']),
    ('get_spec', '读取当前底座配置（target="base"）或某个选题的完整内容（target=选题 slug）。',
     {'target': {'type': 'string'}}, ['target']),
    ('write_base', '写入（整体替换）底座配置：sources 与 stages。会先校验，校验不通过返回问题列表且不保存。',
     {'spec': {'type': 'object', 'description': '{"sources": {...}, "stages": [...]}'}}, ['spec']),
    ('run', '运行底座（target="base"）或某个选题（target=选题 slug），返回运行摘要：每阶段状态、回滚原因、核验违规数与样例、表行数变化、导出。',
     {'target': {'type': 'string'}, 'decisions': {'type': 'object', 'description': '可选，选题口径 {名称: 取值}；取值为空字符串表示运行到该处暂停'}}, ['target']),
    ('write_profile', '写入（整体替换）数据档案 profile.md（Markdown）。',
     {'markdown': {'type': 'string'}}, ['markdown']),
    ('propose_topic', '提交选题卡给研究者确认。研究者在终端确认后状态变为 confirmed；否则返回他的修改意见。修改选题内容后需重新提交确认。',
     {'slug': {'type': 'string', 'description': '英文短标识，如 late-delivery'},
      'card': {'type': 'object', 'description': '字段：' + '、'.join(f'{k}（{v}）' for k, v in project.CARD_FIELDS.items())}}, ['slug', 'card']),
    ('write_topic', '为已确认的选题写入（整体替换）阶段与口径。选题卡未确认时会被拒绝。',
     {'slug': {'type': 'string'}, 'stages': {'type': 'array', 'items': {'type': 'object'}},
      'decisions': {'type': 'object'}}, ['slug', 'stages']),
]


def tool_schemas():
    schemas = []
    for name, description, props, *required in TOOLS:
        schemas.append(dict(type='function', function=dict(name=name, description=description, parameters=dict(
            type='object', properties=props, required=required[0] if required else []))))
    return schemas


def text_table(columns, rows):
    lines = [' | '.join(columns)]
    for row in rows:
        lines.append(' | '.join('NULL' if v is None else project.clip(v, 60) for v in row))
    return '\n'.join(lines)


class Session:
    def __init__(self, root, console, ask):
        self.root = Path(root)
        self.console = console
        self.ask = ask  # ask(prompt) -> str, the researcher's answer at the terminal
        self.raw_db = None
        self.confirmed = set()  # (topic, decision, value) the researcher has confirmed

    # ----- tools -----
    def raw_connection(self):
        if self.raw_db is None:
            db = engine.connect(':memory:')
            base = json.loads((self.root / 'base.json').read_text(encoding='utf-8'))
            raw = project.raw_dir(self.root)
            for table, source in base['sources'].items():
                io.load(db, table, raw / source['file'], {k: v for k, v in source.items() if k != 'columns'})
            self.raw_db = db
        return self.raw_db

    def t_project_state(self):
        return project.state(self.root)

    def t_inspect_data(self):
        db = self.raw_connection()
        base = json.loads((self.root / 'base.json').read_text(encoding='utf-8'))
        result = {}
        for table, source in base['sources'].items():
            prof = profile_table(db, table)
            result[table] = dict(file=source['file'], rows=prof['rows'], columns=[
                dict(name=c['name'], type=c['type'], missing=c['missing'], distinct=c['distinct'],
                     min=project.clip(c['min'], 30), max=project.clip(c['max'], 30), hints=c['hints']) for c in prof['columns']])
        return result

    def t_query(self, sql, target='raw', limit=30):
        limit = max(1, min(int(limit or 30), 200))
        if target == 'raw':
            db, close = self.raw_connection(), False
        else:
            kind = 'base' if target == 'base' else target.removeprefix('topic:')
            found = next((r for r in project.runs(self.root) if r['kind'] == kind and (r['dir'] / engine.DATABASE).is_file()), None)
            if not found:
                return f'没有 {target} 的运行数据库，请先运行'
            db, close = engine.connect(found['dir'] / engine.DATABASE, read_only=True), True
        try:
            cursor = db.execute(sql)
            if cursor.description is None:
                return '语句已执行，无结果集'
            rows = cursor.fetchmany(limit + 1)
            more = '\n（还有更多行，已截断）' if len(rows) > limit else ''
            return text_table([c[0] for c in cursor.description], rows[:limit]) + more
        finally:
            if close:
                db.close()

    def t_get_spec(self, target):
        if target == 'base':
            return json.loads((self.root / 'base.json').read_text(encoding='utf-8'))
        topic, _ = project.load_topic(self.root, target)
        return topic

    def t_write_base(self, spec):
        try:
            normalized = studies.normalize(spec, base=self.root, path='base.json')
        except studies.StudyError as exc:
            return dict(saved=False, problems=exc.problems)
        raw = project.raw_dir(self.root)
        missing = [s['file'] for s in normalized['sources'].values() if not (raw / s['file']).is_file()]
        if missing:
            return dict(saved=False, problems=[f'原始数据目录中没有文件 {m}' for m in missing])
        record.save_json(self.root / 'base.json', spec)
        self.raw_db = None
        return dict(saved=True, stages=[s['name'] for s in normalized['stages']])

    def confirm_decisions(self, target, decisions):
        """Every research definition value must come from the researcher, not the model."""
        topic, _ = project.load_topic(self.root, target)
        specs = topic.get('decisions', {})
        chosen = {}
        for name, value in decisions.items():
            if name not in specs:
                return None, f'选题没有口径 {name}'
            if not value or (target, name, value) in self.confirmed:
                chosen[name] = value or ''
                continue
            options = specs[name].get('options', [])
            labels = specs[name].get('labels', {})
            listing = '；'.join(f'{o}（{labels[o]}）' if o in labels else o for o in options)
            answer = self.ask(f'助理准备按口径「{name}」= {value} 运行。可选：{listing}。输入 y 确认，或输入你要的取值 › ').strip()
            if answer.lower() in ('y', 'yes', '是', '确认', '好', 'ok'):
                answer = value
            if answer not in options:
                return None, answer or '研究者没有确认这个口径'
            self.confirmed.add((target, name, answer))
            chosen[name] = answer
        return chosen, None

    def t_run(self, target, decisions=None):
        if decisions and target != 'base':
            decisions, feedback = self.confirm_decisions(target, decisions)
            if decisions is None:
                return dict(started=False, researcher_feedback=feedback, note='口径未经研究者确认，没有运行；请先和研究者讨论')
        label = 'base' if target == 'base' else target
        out = project.new_out(self.root, label)
        argv = [sys.executable, '-m', 'ew.cli', 'run', str(self.root), '--out', str(out), '--batch']
        if target != 'base':
            argv += ['--topic', target]
        for name, value in (decisions or {}).items():
            argv += ['--decision', f'{name}={value or ""}']
        with self.console.status('运行中…', spinner='dots'):
            result = subprocess.run(argv, capture_output=True, text=True, timeout=3600)
        if not (out / 'run.json').is_file():
            return dict(started=False, error=(result.stderr or result.stdout).strip()[-2000:])
        run = record.load(out)
        return dict(run_id=out.name, **project.summarize(run))

    def t_write_profile(self, markdown):
        (self.root / 'profile.md').write_text(markdown.strip() + '\n', encoding='utf-8')
        return dict(saved=True, chars=len(markdown))

    def t_propose_topic(self, slug, card):
        path = project.topic_path(self.root, slug)
        topic = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else dict(decisions={}, stages=[])
        card = {k: v for k, v in card.items() if k != 'status'}
        topic['card'] = dict(card, status='draft')
        project.save_topic(self.root, slug, topic)
        self.show_card(slug, card)
        answer = self.ask('确认这个选题吗？输入 y 确认，或直接写修改意见（回车表示暂不确认）› ').strip()
        if answer.lower() in ('y', 'yes', '是', '确认', '好', 'ok'):
            topic['card']['status'] = 'confirmed'
            topic['card']['confirmed_at'] = record.now()
            project.save_topic(self.root, slug, topic)
            return dict(slug=slug, status='confirmed')
        return dict(slug=slug, status='draft', researcher_feedback=answer or '研究者暂未确认，请询问他的想法')

    def t_write_topic(self, slug, stages, decisions=None):
        topic, path = project.load_topic(self.root, slug)
        if (topic.get('card') or {}).get('status') != 'confirmed':
            return dict(saved=False, problems=['选题卡尚未经研究者确认，请先用 propose_topic 与研究者确认选题'])
        candidate = dict(topic, stages=stages, decisions=decisions if decisions is not None else topic.get('decisions', {}))
        try:
            studies.normalize(dict(sources={}, base=dict(run='.'), decisions=candidate['decisions'], stages=stages),
                              base=path.parent, path=path)
        except studies.StudyError as exc:
            return dict(saved=False, problems=exc.problems)
        project.save_topic(self.root, slug, candidate)
        return dict(saved=True, stages=[s.get('name') for s in stages])

    # ----- display -----
    def show_card(self, slug, card):
        from rich.panel import Panel
        from rich.table import Table
        table = Table(show_header=False, box=None, pad_edge=False)
        table.add_column(style='bold cyan', no_wrap=True)
        table.add_column()
        for key, label in project.CARD_FIELDS.items():
            value = card.get(key)
            if value:
                table.add_row(label, '；'.join(map(str, value)) if isinstance(value, list) else str(value))
        self.console.print(Panel(table, title=f'选题卡 · {slug}', border_style='yellow', padding=(1, 2)))

    def call(self, name, arguments):
        handler = getattr(self, 't_' + name, None)
        if handler is None:
            return dict(error=f'没有工具 {name}')
        try:
            return handler(**arguments)
        except (project.ProjectError, ValueError, RuntimeError, OSError) as exc:
            return dict(error=str(exc))
        except Exception as exc:  # DuckDB and other errors go back to the model to fix
            return dict(error=f'{type(exc).__name__}: {exc}')


LABELS = {
    'project_state': '查看项目现状', 'inspect_data': '概览原始数据', 'query': '查询', 'get_spec': '读取配置',
    'write_base': '写入底座配置', 'run': '运行', 'write_profile': '写入数据档案', 'propose_topic': '提交选题卡',
    'write_topic': '写入选题阶段',
}


def describe_call(name, args):
    if name == 'query':
        return f'查询 {args.get("target", "raw")}：{project.clip(" ".join(str(args.get("sql", "")).split()), 90)}'
    if name == 'run':
        return '运行 ' + ('数据底座' if args.get('target') == 'base' else f'选题 {args.get("target")}') + (
            f'（口径 {args["decisions"]}）' if args.get('decisions') else '')
    return LABELS.get(name, name)


def describe_result(name, result):
    if isinstance(result, dict):
        if result.get('error'):
            return f'出错：{project.clip(result["error"], 120)}'
        if result.get('saved') is False:
            return '未保存：' + project.clip('；'.join(result.get('problems', [])), 160)
        if name == 'run' and 'status' in result:
            failed = [s['name'] for s in result['stages'] if s['status'] in ('failed', 'needs_decision')]
            return f'{result["run_id"]} · {result["status"]}' + (f' · {failed[0]}' if failed else '')
    return '完成'


class Chat:
    def __init__(self, root, client=None, console=None, ask=None):
        from rich.console import Console
        self.root = Path(root)
        self.console = console or Console(highlight=False)
        self.ask = ask or self.terminal_ask
        self.client = client or Client()
        self.session = Session(self.root, self.console, self.ask)
        self.store = self.root / '.ew' / 'chat.json'
        self.messages = []

    def terminal_ask(self, prompt):
        try:
            import readline  # noqa: F401  (line editing for input())
        except ImportError:
            pass
        self.console.print(prompt, style='bold yellow', end='')
        return input()

    def load(self):
        if self.store.is_file():
            self.messages = json.loads(self.store.read_text(encoding='utf-8'))
        return bool(self.messages)

    def save(self):
        self.store.parent.mkdir(exist_ok=True)
        record.save_json(self.store, self.messages)

    def reply(self, text):
        """Send the researcher's message and run the tool loop until the model answers."""
        from rich.markdown import Markdown
        self.messages.append(dict(role='user', content=text))
        for _ in range(MAX_TOOL_ROUNDS):
            with self.console.status('思考中…', spinner='dots'):
                message = self.client.chat([dict(role='system', content=SYSTEM)] + self.messages, tool_schemas())
            message = {k: v for k, v in message.items() if v is not None}
            self.messages.append(message)
            if message.get('content') and message.get('tool_calls'):
                self.console.print(Markdown(message['content']), style='dim')
            if not message.get('tool_calls'):
                self.console.print(Markdown(message.get('content') or '（没有回复内容）'))
                self.save()
                return message.get('content')
            for call in message['tool_calls']:
                name = call['function']['name']
                try:
                    args = json.loads(call['function'].get('arguments') or '{}')
                except json.JSONDecodeError as exc:
                    args, result = {}, dict(error=f'参数不是合法 JSON：{exc}')
                else:
                    self.console.print(f'  ⚙ {describe_call(name, args)}', style='cyan')
                    if name in ('propose_topic', 'run'):  # may wait for the researcher, so no outer spinner
                        result = self.session.call(name, args)
                    else:
                        with self.console.status(LABELS.get(name, name) + '…', spinner='dots'):
                            result = self.session.call(name, args)
                    self.console.print(f'    → {describe_result(name, result)}', style='dim')
                content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
                if len(content) > TOOL_OUTPUT_LIMIT:
                    content = content[:TOOL_OUTPUT_LIMIT] + '…（输出过长已截断，请缩小查询范围）'
                self.messages.append(dict(role='tool', tool_call_id=call['id'], content=content))
            self.save()
        self.console.print('（本轮工具调用次数过多，已暂停；可以输入「继续」）', style='yellow')
        return None

    def kickoff_text(self):
        state = project.state(self.root)
        return (f'（工作台）研究项目「{state["name"]}」已就绪。原始数据目录：{state["raw"]}，文件：{", ".join(state["files"])}。'
                '请从阶段 A 开始：先理解数据并搭建数据底座，边做边简要告诉我你的发现。')

    def loop(self, fresh=False):
        from rich.panel import Panel
        resumed = False if fresh else self.load()
        if fresh:
            self.messages = []
        self.console.print(Panel(f'研究项目：{project.meta(self.root)["name"]}　模型：{self.client.model}\n'
                                 '直接输入你的想法与助理讨论；/state 查看项目现状，/exit 退出（对话会保存，下次 ew chat 继续）。',
                                 title='Empirical Workbench · 研究助理', border_style='cyan'))
        try:
            if resumed:
                self.console.print('已恢复上次的对话。', style='dim')
            else:
                self.reply(self.kickoff_text())
            while True:
                text = self.ask('\n你 › ').strip()
                if not text:
                    continue
                if text in ('/exit', '/quit', 'exit', 'quit'):
                    break
                if text == '/state':
                    self.console.print_json(json.dumps(project.state(self.root), ensure_ascii=False, default=str))
                    continue
                try:
                    self.reply(text)
                except LLMError as exc:  # keep the conversation; the researcher can retry with 继续
                    self.console.print(f'大模型调用失败：{exc}\n对话已保存，可以输入「继续」重试。', style='red')
        except (EOFError, KeyboardInterrupt):
            pass
        except LLMError as exc:
            self.console.print(f'大模型调用失败：{exc}', style='red')
        finally:
            self.save()
            self.console.print('\n对话已保存。网页工作台查看结果：ew serve --runs ' + str(self.root / 'runs'), style='dim')

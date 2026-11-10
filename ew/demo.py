"""A presenter-paced terminal view over the live SQLite session."""
import sys
import webbrowser
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def keypress():
    if sys.platform == "win32":
        import msvcrt
        return msvcrt.getwch()
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


class Classroom:
    def __init__(self, spec, emit):
        self.console = Console(highlight=False)
        self.spec = spec
        self.emit = emit
        self.names = [stage['name'] for stage in spec['stages']]
        self.guide = spec.get("guide", {})
        self.takeaway = ""
        self.position = -1
        self.sql = []
        self.notes = []

    def header(self):
        self.console.clear()
        self.console.print(self.guide.get('title','Empirical Workbench'),style='bold cyan')
        labels=self.guide.get('steps',self.names)
        if 0 <= self.position < len(labels):
            self.console.print(f'第 {self.position+1}/{len(labels)} 步　{labels[self.position]}',style='bold green')
        self.console.rule(style='cyan')

    def event(self, kind, message):
        if kind == '阶段':
            self.position = self.names.index(message)
            self.sql = []
            self.notes = []
            self.header()
        if kind == 'SQLite':
            self.sql.append(message)
        elif kind == '通过':
            self.notes.append(message)
        elif kind in ('读取','已读取','执行方案','调用工具','工具结果','报告完成','采用口径'):
            if kind == '执行方案' and message == 'main':
                return
            if kind == '调用工具' and 'verify.py' in message:
                message = 'Python · 从原始 CSV 独立复算'
            self.console.print(Text(f'{kind}   {message}',style='green' if kind=='工具结果' else 'cyan'))

    def present(self, title, blocks, details=(), hint='继续执行'):
        mode = ''
        while True:
            self.header()
            self.console.print(Panel(Group(*blocks),title=Text(title),border_style='cyan',padding=(1,2)))
            if mode == 'e':
                for detail in details:
                    self.console.print(detail)
            if mode == 'l':
                for sql in self.sql:
                    self.console.print(Text(sql,style='dim'))
            self.console.print(f'空格 {hint}    E 证据    L SQL    Q 结束',style='bold yellow')
            key = keypress().lower()
            if key in (' ', '\r', '\n'):
                break
            if key in ('q','\x03','\x04',''):
                raise ValueError('讲者结束了现场运行')
            mode = '' if mode == key else key

    def intro(self):
        self.present(self.guide.get('opening','研究问题'), [
            Text(self.guide.get('context','')),
            Text(self.spec.get('question','开始新研究'), style='bold cyan'),
            Text(self.guide.get('route',' → '.join(self.names)))
        ],hint='看看原始记录')

    def finish(self, out):
        self.position=len(self.names)
        self.header()
        self.console.print(Panel(Text(self.takeaway or '各阶段已完成。'), title='今天从这批记录里看到了什么？',padding=(1,2)))
        self.console.print('独立核验已完成。' if self.spec.get('tools',{}).get('verify') else '处理完成。')
        if (out/'report.html').exists():
            path = out/'report.html'
            self.console.print('按 O 在默认浏览器打开研究报告，或按回车返回终端。', style='bold cyan')
            while True:
                key = keypress().lower()
                if key == 'o':
                    if webbrowser.open(path.resolve().as_uri()):
                        self.console.print('已请求浏览器打开报告。')
                    else:
                        self.console.print('请在浏览器中打开本地文件：', path.as_posix())
                    break
                if key in ('q', ' ', '\r', '\n', '\x03', '\x04', ''):
                    break
            self.console.print('报告位置：', path.as_posix(), soft_wrap=True)

    def checkpoint(self, db, stage, when, failure=None):
        pages = stage.get('classroom',{}).get(when,[])
        if not pages and when=='done':
            pages=[dict(title=stage['name'],body='已生成：'+'、'.join(stage.get('exports',{})))]
        for page in pages:
            blocks=[Text(page.get('body',''))]
            details=[Text(x) for x in self.notes]
            if failure:
                details.append(Text(str(failure)))
            for query in page.get('tables',[]):
                sql=query['sql']
                self.sql.append(sql)
                cursor=db.execute(sql)
                rows=cursor.fetchmany(12)
                columns=[col[0] for col in cursor.description]
                self.emit('展示证据',dict(stage=stage['name'],title=page['title'],sql=sql,columns=columns,rows=rows))
                if query.get('explain') and rows:
                    sentence=query['explain'].format_map(dict(zip(columns,rows[0])))
                    blocks.extend([Text(''),Text(sentence,style='bold green')])
                    self.takeaway=sentence
                    continue
                table=Table(show_edge=False,header_style='bold cyan',pad_edge=False)
                for col in columns:
                    table.add_column(col,overflow='fold')
                for row in rows:
                    table.add_row(*(Text(str(x) if x is not None else '缺失') for x in row))
                (details if query.get('detail') else blocks).append(table)
            if page.get('lesson'):
                blocks.extend([Text(''),Text(page['lesson'],style='green')])
            if self.notes:
                details.insert(0,Text('已通过检查',style='bold green'))
            self.present(page['title'],blocks,details,page.get('next','继续执行'))

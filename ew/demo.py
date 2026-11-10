"""A presenter-paced terminal view over the live SQLite session."""
import sys
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
        self.position = -1
        self.sql = []
        self.notes = []

    def header(self):
        self.console.clear()
        self.console.print('EMPIRICAL WORKBENCH   /   现场研究', style='bold cyan')
        nav = Text()
        for i, name in enumerate(self.names):
            marker = '✓' if i < self.position else '●' if i == self.position else '○'
            nav.append(f'{marker} {name}   ', style='bold cyan' if i == self.position else 'green' if i < self.position else 'dim')
        self.console.print(nav)
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
        self.present('研究问题', [Text(self.spec.get('question','开始新研究'),style='bold'),
            Text('\n'+'\n'.join(self.names)),Text('\n输入：原始表    交付：分析数据、统计底表与核验记录')],hint='读取原始表')

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
                table=Table(show_edge=False,header_style='bold cyan',pad_edge=False)
                for col in columns:
                    table.add_column(col,overflow='fold')
                for row in rows:
                    table.add_row(*(Text(str(x) if x is not None else '缺失') for x in row))
                (details if query.get('detail') else blocks).append(table)
            if self.notes:
                details.insert(0,Text('已通过检查',style='bold green'))
            self.present(page['title'],blocks,details,page.get('next','继续执行'))

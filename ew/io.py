"""Read sources into DuckDB and write exports, by file extension.

Native: .csv/.tsv/.txt (any encoding; non-UTF-8 such as GBK is transcoded), .parquet,
and .csv.gz / .parquet exports. Optional (pip install "empirical-workbench[formats]"):
.xlsx/.xls and Stata .dta, both directions.
"""
import codecs
import shutil
import tempfile
from pathlib import Path

TEXT = ('.csv', '.tsv', '.txt', '.gz')
PANDAS = ('.xlsx', '.xls', '.dta')
FALLBACK_ENCODING = 'gb18030'  # superset of GBK/GB2312, common in CSMAR/Wind/CNRDS exports


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def ident(name):
    return '"' + str(name).replace('"', '""') + '"'


def detect_encoding(path, declared=None):
    if declared:
        return codecs.lookup(declared).name
    decoder = codecs.getincrementaldecoder('utf-8-sig')()
    with Path(path).open('rb') as stream:
        try:
            for block in iter(lambda: stream.read(1 << 20), b''):
                decoder.decode(block)
            decoder.decode(b'', final=True)
            return 'utf-8'
        except UnicodeDecodeError:
            return FALLBACK_ENCODING


def pandas():
    try:
        import pandas
    except ImportError:
        raise RuntimeError('读写 Excel / Stata 文件需要 pandas：pip install "empirical-workbench[formats]"') from None
    return pandas


def relation_sql(db, path, source, scratch):
    """Return (SQL relation over the file, encoding or None)."""
    suffix = path.suffix.lower()
    if suffix == '.parquet':
        return f'read_parquet({quote(path)})', None
    if suffix in PANDAS:
        pd = pandas()
        frame = pd.read_stata(path, convert_categoricals=False) if suffix == '.dta' else pd.read_excel(path, sheet_name=source.get('sheet', 0))
        db.register('_ew_frame', frame)
        return '_ew_frame', None
    if suffix not in TEXT:
        raise ValueError(f'{path.name}：不支持的文件类型 {suffix}')
    encoding = None
    if suffix != '.gz':
        encoding = detect_encoding(path, source.get('encoding'))
        if encoding not in ('utf-8', 'utf-8-sig'):
            target = scratch / (path.stem + '.utf8' + path.suffix)
            with path.open('r', encoding=encoding, newline='') as src, target.open('w', encoding='utf-8', newline='') as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            path = target
    options = ['header=true', 'sample_size=-1']
    if source.get('delimiter'):
        options.append(f'delim={quote(source["delimiter"])}')
    elif path.suffix.lower() == '.tsv':
        options.append("delim='\\t'")
    if source.get('types'):
        options.append('types={' + ','.join(f'{quote(k)}:{quote(v)}' for k, v in source['types'].items()) + '}')
    return f'read_csv({quote(path)}, {", ".join(options)})', encoding


def load(db, table, path, source):
    """Create table from a source file with only the declared columns; returns metadata."""
    with tempfile.TemporaryDirectory(prefix='ew-') as tmp:
        relation, encoding = relation_sql(db, Path(path), source, Path(tmp))
        available = [row[0] for row in db.execute(f'DESCRIBE SELECT * FROM {relation}').fetchall()]
        columns = source.get('columns') or available
        missing = [c for c in columns if c not in available]
        if missing:
            raise ValueError(f'{table}：{Path(path).name} 缺少字段 {", ".join(missing)}')
        db.execute(f'CREATE TABLE {ident(table)} AS SELECT {", ".join(map(ident, columns))} FROM {relation}')
        if relation == '_ew_frame':
            db.unregister(relation)
    types = dict(db.execute(f'SELECT column_name, data_type FROM information_schema.columns '
                            f'WHERE table_name = {quote(table)} ORDER BY ordinal_position').fetchall())
    rows = db.execute(f'SELECT count(*) FROM {ident(table)}').fetchone()[0]
    return dict(columns=columns, types=types, rows=rows, encoding=encoding)


def export(db, query, path):
    """Write a query result to path (format from extension); returns {file, rows, columns}."""
    query = query.strip().rstrip(';')
    columns = [c[0] for c in db.execute(f'SELECT * FROM ({query}) LIMIT 0').description]
    name = path.name.lower()
    if name.endswith(('.csv', '.csv.gz')):
        rows = db.execute(f'COPY ({query}) TO {quote(path)} (HEADER, DELIMITER \',\')').fetchone()[0]
    elif name.endswith('.parquet'):
        rows = db.execute(f'COPY ({query}) TO {quote(path)} (FORMAT parquet)').fetchone()[0]
    elif name.endswith(('.dta', '.xlsx')):
        pandas()
        frame = db.execute(query).df()
        if name.endswith('.dta'):
            frame.to_stata(path, write_index=False, version=118)
        else:
            frame.to_excel(path, index=False)
        rows = len(frame)
    else:
        raise ValueError(f'导出文件 {path.name} 的格式不受支持（可用 .csv .csv.gz .parquet .dta .xlsx）')
    return dict(file=path.name, rows=rows, columns=columns)

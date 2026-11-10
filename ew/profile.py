"""Column profiles of loaded tables, shared by `ew inspect` and the research agent."""
from . import io


def profile_table(db, table):
    """Column profile of a loaded table: type, missing share, distinct values, range, hints."""
    rows = db.execute(f'SELECT count(*) FROM {io.ident(table)}').fetchone()[0]
    columns = []
    for name, ctype, lo, hi, distinct, null_pct in db.execute(
            f'SELECT column_name, column_type, min, max, approx_unique, null_percentage FROM (SUMMARIZE {io.ident(table)})').fetchall():
        col = io.ident(name)
        missing = db.execute(f'SELECT count(*) - count({col}) FROM {io.ident(table)}').fetchone()[0]
        hints = []
        if missing == 0 and rows and db.execute(f'SELECT count(DISTINCT {col}) FROM {io.ident(table)}').fetchone()[0] == rows:
            hints.append('候选主键')
        if ctype == 'VARCHAR' and rows:
            zeros, numeric, filled = db.execute(
                f"SELECT count_if(regexp_full_match({col}, '0[0-9]+')), count(TRY_CAST(replace({col}, ',', '') AS DOUBLE)), count({col}) "
                f'FROM {io.ident(table)}').fetchone()
            if zeros:
                hints.append('含前导零代码，应保持文本')
            elif filled and numeric == filled:
                hints.append('疑似数值被读成文本')
        columns.append(dict(name=name, type=ctype, missing=missing, missing_share=round(missing / rows, 4) if rows else 0,
                            distinct=distinct, min=lo, max=hi, hints=hints))
    return dict(rows=rows, columns=columns)

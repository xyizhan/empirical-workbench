"""Independent calculations from source CSVs; checks both study definitions."""
import csv
import gzip
import math
import json
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from statistics import mean

raw, run = map(Path, sys.argv[1:3])
manifest = json.loads((run/'run.json').read_text())
mode = manifest['decisions']['延误定义']['value']


def rows(name):
    with (raw/f'olist_{name}_dataset.csv').open(newline='', encoding='utf-8-sig') as f:
        yield from csv.DictReader(f)


scores = defaultdict(list)
for row in rows('order_reviews'):
    scores[row['order_id']].append(int(row['review_score']))
payments = defaultdict(int)
for row in rows('order_payments'):
    payments[row['order_id']] += int(100 * Decimal(row['payment_value']))
groups = defaultdict(list)
expected = {}
for row in rows('orders'):
    k = row['order_id']
    delivered = row['order_delivered_customer_date']
    due = row['order_estimated_delivery_date']
    start = row['order_purchase_timestamp']
    rated = bool(row['order_status']=='delivered' and delivered and due and start and
                 datetime.fromisoformat(delivered)>=datetime.fromisoformat(start) and scores.get(k))
    group = None
    if rated:
        group = int(delivered[:10]>due[:10] if mode=='calendar' else datetime.fromisoformat(delivered)>datetime.fromisoformat(due))
        groups[group].append(mean(scores[k]))
    expected[k] = (int(rated),group)
with gzip.open(run/'分析数据.csv.gz','rt',newline='') as f:
    for row in csv.DictReader(f):
        k=row['order_id']
        wanted=expected.pop(k)
        assert (int(row['rated']),int(row['late']) if row['late'] else None)==wanted,k
        assert (int(row['paid_cents']) if row['paid_cents'] else None)==payments.get(k),k
assert not expected
with (run/'图表底表.csv').open() as f:
    table=list(csv.DictReader(f))
assert len(table)==len(groups)
for row in table:
    values=groups[int(row['late'])]
    assert len(values)==int(row['n']) and math.isclose(mean(values),float(row['mean_score']),rel_tol=0,abs_tol=1e-10)
    assert sum(x<=2 for x in values)==int(row['low_score_n'])
    assert sum(x>=4 for x in values)==int(row['high_score_n'])
print(f'{mode} 逐单主键、入样、组别、支付金额及两组人数、均分、低高评分数通过')

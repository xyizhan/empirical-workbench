"""Olist study report builder: the reader-facing Quarto manuscript for a verified run.

Loaded by ew via study.json {"report": {"builder": "report.py"}}.
"""
import csv
from html import escape


def build(out, run):
    def rows(name):
        with (out / (name + '.csv')).open(newline='', encoding='utf-8') as f:
            return list(csv.DictReader(f))

    flow = rows('样本筛选')[0]
    counts = [int(flow[k]) for k in ('all_orders', 'delivered', 'fulfillment', 'rated')]
    groups = sorted(rows('图表底表'), key=lambda r: int(r['late']))
    by_branch = {(r['branch'], r['late']): r for r in rows('探索对照')}
    gaps = {k: float(by_branch[k, '0']['mean_score']) - float(by_branch[k, '1']['mean_score'])
            for k in 'ABC'}
    case = rows('连接诊断')[0]
    choice = rows('口径比较')[0]
    boundary = rows('边界记录')[0]
    calendar = run['decisions']['延误定义']['value'] == 'calendar'
    definition = ('按日期比较，预计当天签收算准时' if calendar else
                  '按完整时刻比较，超过预计时刻即算晚送')
    labels = ['准时送达', '晚于预计送达']
    shares = [100 * int(r['low_score_n']) / int(r['n']) for r in groups]
    score_bars = ''
    for label, r, share in zip(labels, groups, shares):
        score_bars += (f'<div class="series"><b>{label}</b><span>{int(r["n"]):,} 单</span>'
                       f'<div class="track"><i style="width:{share:.4f}%"></i></div>'
                       f'<strong>{share:.1f}%</strong></div>')
    stages = ''
    for i, (label, n) in enumerate(zip(['所有订单','状态为已送达','日期足以判断履约','买家留下了评分'], counts)):
        change = '从这里开始' if i == 0 else f'本步减少 {counts[i-1]-n:,} 单'
        stages += f'<div><small>{change}</small><strong>{n:,}</strong><span>{label}</span></div>'
    contrast = ''
    for key, label in zip('ABC', ['全部可比较订单，取全部评分','留下有收货后评价的订单，仍取全部评分','同一批订单，只取收货后的评分']):
        n = sum(int(by_branch[key, side]['n']) for side in '01')
        contrast += (f'<div class="branch"><div><b>{label}</b><small>{n:,} 单</small></div>'
                     f'<div class="track"><i style="width:{abs(gaps[key])/4*100:.4f}%"></i></div>'
                     f'<strong>{gaps[key]:.3f} 分</strong></div>')
    def figure(content):
        return '\n```{=html}\n' + content + '\n```\n'

    style = """<style>
body{color:#243632;background:#fffefa}main{max-width:850px}h1,h2{color:#153f39}h1{letter-spacing:-.03em}h2{margin-top:2.8rem}p{line-height:1.85}figure.story{margin:1.3rem 0;padding:1.25rem;background:#edf4ef;border-left:4px solid #176c60}figure.story figcaption{color:#334943;font-size:.95rem}.flow{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem}.flow strong,.flow span,small{display:block}.flow strong{font-size:1.65rem}.flow small,.branch small{color:#50645e}.series,.branch{display:grid;align-items:center;gap:.7rem;margin:.9rem 0}.series{grid-template-columns:8em 6em 1fr 4em}.branch{grid-template-columns:minmax(13em,1.2fr) 1fr 5em}.track{height:14px;background:#d4e1d9}.track i{display:block;background:#227769;height:100%}.series:nth-child(2) i{background:#a65436}.branch:first-child i{background:#a65436}@media(max-width:600px){.flow{grid-template-columns:1fr 1fr}.series,.branch{grid-template-columns:1fr auto}.branch .track{grid-row:auto}.branch strong{grid-column:2}.series .track{min-width:7em}}
</style>"""
    return f"""---
title: "包裹晚到，买家会打几分？"
subtitle: "从巴西 Olist 的一笔网购，读懂配送时间与评分"
lang: zh
format:
  html:
    embed-resources: true
    toc: true
    toc-title: 阅读导航
---

{figure(style)}

顾客下单时会看到预计送达时间，包裹签收后则有实际送达记录。巴西电商平台 Olist 的公开数据还记下了买家给订单的评分，1 分最低，5 分最高。我们想知道：在能够判断配送早晚、也有评分的订单里，晚送订单的买家平均打几分？

**本次比较了 {counts[-1]:,} 笔订单。准时组平均 {float(groups[0]['mean_score']):.2f} 分，晚送组平均 {float(groups[1]['mean_score']):.2f} 分。** 下文沿着一笔订单说明这些数字怎样算出来，以及换一批订单后，为什么差距会缩小。

## 一笔网购，为什么会出现在四份文件里？

订单表记下单和签收，商品表记每件商品，支付表记每笔付款，评价表记买家打的分。同一个订单号把这些记录连起来。比如订单 `{case['order_id'][:8]}…` 买了 {case['item_n']} 件商品、分 {case['payment_n']} 笔付款。直接把每件商品和每次付款配在一起，就会出现 {int(case['item_n'])*int(case['payment_n'])} 行，实付的 **{int(case['verified_cents'])/100:.2f} 雷亚尔**会被加成 **{int(case['naive_cents'])/100:.2f} 雷亚尔**。

我们先分别按订单汇总商品、支付和评价，再拼回订单表。这样每一行代表一笔订单。一单有多条评价时先算该单平均分，两组比较时每单占一票。

## 哪些订单能回答这个问题？

{figure('<figure class="story"><div class="flow">'+stages+'</div><figcaption>图 1　从左到右沿用上一步留下的订单。每一步都要满足比较所需的一项条件。</figcaption></figure>')}

已送达订单中，有 {counts[1]-counts[2]:,} 单未能进入履约比较；本次质量记录中，已送达却缺签收日期的有 {sum(int(r['n']) for r in rows('质量处置') if r['quality']=='missing_actual'):,} 单。即使知道买家打了几分，没有签收日期也无法判断它属于哪一组。随后又有 {counts[2]-counts[3]:,} 单因没有评分而退出比较。它们的原记录均保留在全量数据里。

**怎样算晚送？** 本次选择{definition}。例如一笔订单预计在 {escape(boundary['order_estimated_delivery_date'])} 送达，实际于 {escape(boundary['order_delivered_customer_date'])} 签收。按日期它算准时，按时刻它算晚送。两种定义会让 {int(choice['switched']):,} 笔订单改变分组。

## 平均分之外，每组有多少买家给了低分？

{figure('<figure class="story">'+score_bars+'<figcaption>图 2　低分指一笔订单的平均评分不超过 2 分。横条占满表示 100%，每组以自己的订单数为分母。</figcaption></figure>')}

换成直观的人数：每 100 笔准时订单里，约 {round(shares[0])} 笔获低分；每 100 笔晚送订单里，约 {round(shares[1])} 笔获低分。组间均分相差 **{gaps['A']:.3f} 分**，低分占比也显示出差别。

## 如果只听收货后的评价，差距还这么大吗？

有些评价写在签收前。只看收货后评价，会同时改变两件事：有些订单被筛掉，有些留下的订单要改用部分评分。为了弄清哪一步影响更大，我们在中间多算了一次。

{figure('<figure class="story">'+contrast+'<figcaption>图 3　每行是准时组均分减去晚送组均分。比较前两行，只改变订单范围；比较后两行，保持同一批订单，只改变评分取法。横条使用相同的 0–4 分刻度。</figcaption></figure>')}

只换订单，差距就从 **{gaps['A']:.3f}** 变为 **{gaps['B']:.3f}** 分；对同一批订单改用收货后的评分，差距为 **{gaps['C']:.3f}** 分。本次变化主要发生在筛选订单时。这个发现也限定了结论的范围：我们观察到了留下评价的顾客之间的差异，订单构成和评价时机都可能影响比较，不能把均分差直接解释为晚送造成的损失。

## 数据与复核

数据来自 [Olist 巴西电商公开数据](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)。下列文件与本报告保存在同一运行目录中。

- [样本筛选人数](样本筛选.csv) · [逐组订单数与平均分](图表底表.csv) · [三次比较的统计底表](探索对照.csv)
- [独立复算记录](verify.log) · [本次运行和研究者选择](run.json)
"""

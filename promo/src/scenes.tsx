import React from 'react';
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig } from 'remotion';
import { Chip, Count, Glass, Headline, Mono } from './parts';
import { C, MONO, SANS, pop, prog, typed } from './theme';

/* ---------- 1. Hook: a pile of unfamiliar fields ---------- */
const FIELDS = ['order_id', 'customer_unique_id', 'order_purchase_timestamp', 'review_score', 'payment_installments', 'freight_value',
  'seller_zip_code_prefix', 'product_weight_g', 'order_estimated_delivery_date', 'geolocation_lat', 'payment_sequential', 'order_item_id',
  'review_answer_timestamp', 'customer_state', 'price', 'product_category_name', 'order_status', 'seller_id', 'payment_type', 'review_id'];

export const Hook: React.FC = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const gather = prog(f, 56, 80);
  const a = pop(f, fps, 6);
  const b = pop(f, fps, 24);
  return (
    <AbsoluteFill style={{ fontFamily: SANS }}>
      {FIELDS.map((name, i) => {
        const angle = (i / FIELDS.length) * Math.PI * 2 + i;
        const radius = 380 + ((i * 89) % 260);
        const drift = f * (0.6 + (i % 4) * 0.25);
        const x = 960 + Math.cos(angle + drift / 400) * (radius + drift * 0.6);
        const y = 540 + Math.sin(angle + drift / 400) * (radius * 0.55);
        const depth = 0.55 + ((i * 53) % 10) / 20;
        const appear = prog(f, i * 1.5, i * 1.5 + 14);
        const gx = interpolate(gather, [0, 1], [x, 960]);
        const gy = interpolate(gather, [0, 1], [y, 540]);
        return (
          <div key={name} style={{ position: 'absolute', left: gx, top: gy, transform: `translate(-50%,-50%) rotate(${(i % 2 ? 1 : -1) * (6 + (i % 5) * 3) * (1 - gather)}deg) scale(${depth * (1 - gather * 0.7)})`,
            opacity: appear * (1 - gather) * (0.35 + depth * 0.6), filter: `blur(${(1.2 - depth) * 3}px)`, fontFamily: MONO, fontSize: 30, color: i % 3 ? C.sub : C.cyan,
            padding: '8px 16px', border: `1px solid ${C.line}`, borderRadius: 10, background: 'rgba(15,22,36,0.7)', whiteSpace: 'nowrap' }}>
            {name}
          </div>
        );
      })}
      <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center', transform: `scale(${1 + gather * 0.15})`, opacity: 1 - gather }}>
        <div style={{ fontSize: 92, fontWeight: 800, color: C.text, opacity: a, transform: `translateY(${(1 - a) * 50}px)` }}>拿到一份陌生的数据</div>
        <div style={{ fontSize: 92, fontWeight: 800, marginTop: 18, opacity: b, transform: `translateY(${(1 - b) * 50}px)`,
          background: `linear-gradient(90deg, ${C.blue}, ${C.cyan})`, WebkitBackgroundClip: 'text', color: 'transparent' }}>
          从哪里下手？
        </div>
        <div style={{ marginTop: 40, fontSize: 30, color: C.sub, opacity: prog(f, 32, 44), display: 'flex', gap: 28 }}>
          <span><Count to={9} start={32} dur={18} /> 张表</span>
          <span><Count to={52} start={32} dur={18} /> 个字段</span>
          <span><Count to={1550922} start={32} dur={22} /> 行</span>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/* ---------- 2. The assistant reads the data ---------- */
const NODES = [
  { id: 'orders', label: 'orders 订单', sub: '一行一单', n: 99441, x: 520, y: 640, main: true },
  { id: 'items', label: 'items 商品明细', sub: '一单多行', n: 112650, x: 200, y: 420 },
  { id: 'payments', label: 'payments 支付', sub: '一单多笔', n: 103886, x: 200, y: 860 },
  { id: 'reviews', label: 'reviews 评价', sub: '一单多条', n: 99224, x: 840, y: 420 },
  { id: 'customers', label: 'customers 顾客', sub: '一单一人', n: 99441, x: 840, y: 860 },
];
const REL: Record<string, string> = { items: '1 : N', payments: '1 : N', reviews: '1 : N', customers: '1 : 1' };
const MESSAGES = [
  { tool: true, text: '⚙ 查询 raw：select order_id, count(*) … having count(*) > 1' },
  { text: 'orders 一行一单，order_id 唯一 —— 这是分析的主键。' },
  { text: 'items / payments 都是一单多行：先按订单汇总，再合并，避免行数膨胀。' },
  { text: '明细全部能对上订单，匹配率 100%，没有孤儿记录。' },
  { warn: true, text: 'review_id 有 814 个重复，不能当主键。' },
];

export const Understand: React.FC = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const zoom = interpolate(f, [0, 110], [1.04, 1]);
  return (
    <AbsoluteFill>
      <Headline kicker="01 · 读懂数据" title="AI 助理先摸清每张表" />
      <div style={{ position: 'absolute', left: 60, top: 40, width: 1040, height: 1040, transform: `scale(${zoom})`, transformOrigin: '50% 60%' }}>
        <svg width={1040} height={1040} style={{ position: 'absolute', inset: 0 }}>
          <defs>
            <linearGradient id="edge" x1="0" x2="1"><stop offset="0" stopColor={C.blue} /><stop offset="1" stopColor={C.cyan} /></linearGradient>
          </defs>
          {NODES.filter((n) => !n.main).map((n, i) => {
            const o = NODES[0];
            const len = Math.hypot(n.x - o.x, n.y - o.y);
            const p = prog(f, 14 + i * 5, 34 + i * 5);
            return (
              <g key={n.id}>
                <line x1={o.x} y1={o.y} x2={n.x} y2={n.y} stroke="url(#edge)" strokeWidth={3} strokeDasharray={len} strokeDashoffset={len * (1 - p)} opacity={0.85} />
                <circle cx={o.x + (n.x - o.x) * ((f * 0.02 + i * 0.25) % 1)} cy={o.y + (n.y - o.y) * ((f * 0.02 + i * 0.25) % 1)} r={5} fill={C.cyan} opacity={p} />
              </g>
            );
          })}
        </svg>
        {NODES.filter((n) => !n.main).map((n, i) => {
          const o = NODES[0];
          const p = prog(f, 26 + i * 5, 40 + i * 5);
          return (
            <div key={n.id + 'r'} style={{ position: 'absolute', left: (o.x + n.x) / 2, top: (o.y + n.y) / 2, transform: `translate(-50%,-50%) scale(${p})`,
              fontFamily: MONO, fontSize: 24, fontWeight: 700, color: REL[n.id] === '1 : 1' ? C.green : C.amber, background: C.bg, padding: '4px 12px', borderRadius: 8, border: `1px solid ${C.line}` }}>
              {REL[n.id]}
            </div>
          );
        })}
        {NODES.map((n, i) => {
          const s = pop(f, fps, n.main ? 2 : 10 + i * 4);
          return (
            <Glass key={n.id} glow={n.main ? C.blue : C.cyan} style={{ position: 'absolute', left: n.x, top: n.y, transform: `translate(-50%,-50%) scale(${s})`, padding: '18px 24px',
              minWidth: n.main ? 280 : 250, border: n.main ? `2px solid ${C.blue}` : undefined }}>
              <div style={{ fontFamily: MONO, fontSize: n.main ? 28 : 24, fontWeight: 700 }}>{n.label}</div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontSize: 21, color: C.sub, gap: 16 }}>
                <span>{n.sub}</span><Count to={n.n} start={(n.main ? 2 : 10 + i * 4) + 4} dur={22} style={{ color: C.text }} />
              </div>
            </Glass>
          );
        })}
      </div>
      <Glass style={{ position: 'absolute', left: 1130, top: 250, width: 680, height: 690, padding: 28, transform: `translateX(${(1 - prog(f, 4, 22)) * 80}px)`, opacity: prog(f, 4, 22) }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 24, fontWeight: 700, color: C.sub, marginBottom: 22 }}>
          <span style={{ width: 12, height: 12, borderRadius: 6, background: C.green, boxShadow: `0 0 ${10 + Math.sin(f / 4) * 6}px ${C.green}` }} />
          研究助理 · ew chat
        </div>
        {MESSAGES.map((m, i) => {
          const start = 14 + i * 17;
          const s = pop(f, fps, start, 18);
          if (f < start) return null;
          return (
            <div key={i} style={{ marginBottom: 16, opacity: s, transform: `translateY(${(1 - s) * 20}px)`, fontSize: m.tool ? 20 : 25, lineHeight: 1.5,
              fontFamily: m.tool ? MONO : SANS, color: m.tool ? C.cyan : m.warn ? C.amber : C.text,
              padding: m.tool ? 0 : '12px 18px', borderRadius: 14, background: m.tool ? 'none' : 'rgba(79,140,255,0.10)', borderLeft: m.tool ? 'none' : `3px solid ${m.warn ? C.amber : C.blue}` }}>
              {typed(m.text, f, start, 60)}
            </div>
          );
        })}
      </Glass>
    </AbsoluteFill>
  );
};

/* ---------- 3. Data base: flag, never drop; failed merges roll back ---------- */
const ROWS = [
  ['06875ab7…', 'delivered', '2017-09-20', 4],
  ['9e6bc602…', 'delivered', null, 5],
  ['9edb4a65…', 'canceled', null, null],
  ['6e3c8fe2…', 'delivered', '2018-03-29', 1],
  ['bca16cf3…', 'delivered', '2018-01-22', null],
  ['0005a1a1…', 'delivered', '2018-03-29', 2],
];
const FLAGS: Record<number, [string, string]> = { 1: ['缺签收日期', C.amber], 2: ['未成交', C.violet], 3: ['晚于预计', C.red], 4: ['无评价', C.cyan], 5: ['晚于预计', C.red] };

export const Base: React.FC = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const shot = prog(f, 44, 70);
  const ring = prog(f, 66, 86);
  return (
    <AbsoluteFill>
      <Headline kicker="02 · 数据底座" title="只标记，不删除" accent={C.cyan} />
      <Glass style={{ position: 'absolute', left: 120, top: 300, width: 820, padding: '22px 26px', transform: `translateY(${(1 - prog(f, 2, 20)) * 60}px) scale(${1 - shot * 0.06})`,
        opacity: prog(f, 2, 20) * (1 - shot * 0.25), transformOrigin: 'left center' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '170px 150px 170px 80px 1fr', fontSize: 21, color: C.muted, fontWeight: 700, paddingBottom: 12, borderBottom: `1px solid ${C.line}` }}>
          <span>order_id</span><span>状态</span><span>签收日期</span><span>评分</span><span>质量标记</span>
        </div>
        {ROWS.map((r, i) => {
          const flag = FLAGS[i];
          const s = pop(f, fps, 14 + i * 4, 13);
          return (
            <div key={i} style={{ display: 'grid', gridTemplateColumns: '170px 150px 170px 80px 1fr', alignItems: 'center', height: 58, fontSize: 22, borderBottom: `1px solid ${C.line}`,
              background: flag && s > 0.5 ? `${flag[1]}0d` : 'transparent' }}>
              <Mono style={{ color: C.sub }}>{r[0]}</Mono>
              <span>{r[1]}</span>
              <Mono style={{ color: r[2] ? C.text : C.muted }}>{r[2] ?? '缺失'}</Mono>
              <span style={{ color: r[3] ? C.text : C.muted }}>{r[3] ?? '—'}</span>
              <span>{flag && <Chip color={flag[1]} style={{ transform: `scale(${s})`, fontSize: 19, padding: '4px 12px' }}>⚑ {flag[0]}</Chip>}</span>
            </div>
          );
        })}
        <div style={{ marginTop: 18, fontSize: 22, color: C.sub, display: 'flex', gap: 26, opacity: prog(f, 36, 48) }}>
          <span><Count to={7827} start={36} style={{ color: C.red, fontWeight: 800 }} /> 晚于预计</span>
          <span><Count to={775} start={36} style={{ color: C.violet, fontWeight: 800 }} /> 无商品</span>
          <span><Count to={768} start={36} style={{ color: C.cyan, fontWeight: 800 }} /> 无评价</span>
          <span style={{ color: C.green }}>全部保留，交给选题决定</span>
        </div>
      </Glass>
      <div style={{ position: 'absolute', left: 1010, top: 250, width: 800, transform: `perspective(1600px) rotateY(${interpolate(shot, [0, 1], [-38, -9])}deg) translateX(${(1 - shot) * 380}px)`,
        opacity: shot, transformOrigin: 'left center' }}>
        <div style={{ position: 'relative', borderRadius: 18, overflow: 'hidden', boxShadow: '0 40px 90px rgba(0,0,0,0.6)', border: `1px solid ${C.line}` }}>
          <Img src={staticFile('asset-attempts.png')} style={{ width: 800, display: 'block' }} />
          <div style={{ position: 'absolute', left: 8, top: 32, width: 784, height: 302, border: `4px solid ${C.red}`, borderRadius: 14, opacity: ring,
            boxShadow: `0 0 ${30 * ring}px ${C.red}`, clipPath: `inset(0 ${(1 - ring) * 100}% 0 0)` }} />
          <div style={{ position: 'absolute', left: 8, top: 346, width: 784, height: 180, border: `4px solid ${C.green}`, borderRadius: 14, opacity: prog(f, 84, 98),
            boxShadow: `0 0 26px ${C.green}` }} />
        </div>
        <div style={{ display: 'flex', gap: 14, marginTop: 22, fontFamily: SANS }}>
          <Chip color={C.red} style={{ opacity: ring, transform: `translateY(${(1 - ring) * 16}px)` }}>✕ 直接连接：<Count to={12489} start={70} dur={18} /> 行违规 → 自动回滚</Chip>
          <Chip color={C.green} style={{ opacity: prog(f, 84, 98) }}>✓ 先汇总再合并 · 采用</Chip>
        </div>
      </div>
    </AbsoluteFill>
  );
};

/* ---------- 4. One base, many topics ---------- */
const TOPICS = [
  { title: '配送延误 × 顾客评分', sub: '晚到的订单，评分低多少？', color: C.blue },
  { title: '分期期数 × 客单价', sub: '分期越多，买得越贵？', color: C.violet },
  { title: '首单体验 × 复购', sub: '第一次的体验，决定回不回来？', color: C.green },
];

export const Topics: React.FC = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const base = pop(f, fps, 2);
  return (
    <AbsoluteFill>
      <Headline kicker="03 · 讨论选题" title="一份底座，随时换题" accent={C.violet} />
      <svg width={1920} height={1080} style={{ position: 'absolute', inset: 0 }}>
        {TOPICS.map((t, i) => {
          const y = 420 + i * 210;
          const p = prog(f, 12 + i * 6, 32 + i * 6);
          const d = `M 660 640 C 880 640, 880 ${y}, 1110 ${y}`;
          return <path key={i} d={d} fill="none" stroke={t.color} strokeWidth={4} strokeDasharray={700} strokeDashoffset={700 * (1 - p)} opacity={0.9} />;
        })}
      </svg>
      <div style={{ position: 'absolute', left: 480, top: 640, transform: `scale(${base})` }}>
        {[2, 1, 0].map((k) => (
          <div key={k} style={{ position: 'absolute', left: -170 + k * 14, top: -125 + k * 14, width: 340, height: 250, borderRadius: 22,
            background: `rgba(56,213,232,${0.06 + (2 - k) * 0.05})`, border: `1px solid ${C.cyan}55` }} />
        ))}
        <Glass glow={C.cyan} style={{ position: 'relative', width: 340, height: 250, left: -170, top: -125, padding: 26, border: `2px solid ${C.cyan}` }}>
          <div style={{ fontSize: 34, fontWeight: 800 }}>数据底座</div>
          <div style={{ fontFamily: MONO, fontSize: 20, color: C.sub, marginTop: 12, lineHeight: 1.55 }}>fact_orders<br />dim_customers<br />dim_sellers<br />quality_summary</div>
        </Glass>
      </div>
      {TOPICS.map((t, i) => {
        const s = pop(f, fps, 24 + i * 6);
        return (
          <Glass key={i} glow={t.color} style={{ position: 'absolute', left: 1110, top: 420 + i * 210, width: 660, padding: '22px 28px', transform: `translateY(-50%) translateX(${(1 - s) * 60}px)`,
            opacity: s, borderLeft: `5px solid ${t.color}` }}>
            <div style={{ fontSize: 34, fontWeight: 800 }}>{t.title}</div>
            <div style={{ fontSize: 24, color: C.sub, marginTop: 6 }}>{t.sub}</div>
          </Glass>
        );
      })}
      <div style={{ position: 'absolute', left: 120, top: 900, fontSize: 28, color: C.sub, opacity: prog(f, 44, 58) }}>
        换题不用重跑底座 · 每个选题各自记录、各自可复现
      </div>
    </AbsoluteFill>
  );
};

/* ---------- 5. The researcher confirms the topic card ---------- */
const CARD = [
  ['研究问题', '配送是否延误，与顾客评分有怎样的关系？'],
  ['分析单位', '订单（order_id）'],
  ['被解释变量', '差评：订单平均评分 ≤ 3'],
  ['核心解释变量', '是否晚到 · 延误天数'],
  ['样本范围', '已交付且有评价的订单'],
  ['待定口径', '晚到怎么算：按自然日，还是按精确时刻？'],
];

export const Card: React.FC = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const stamp = pop(f, fps, 58, 9);
  const answer = f >= 50 ? 'y' : '';
  return (
    <AbsoluteFill>
      <Headline kicker="04 · 研究者拍板" title="选题卡，由你确认" accent={C.amber} />
      <Glass glow={C.amber} style={{ position: 'absolute', left: 420, top: 270, width: 1080, padding: '30px 40px', opacity: prog(f, 0, 12), transform: `translateY(${(1 - prog(f, 0, 14)) * 50}px)` }}>
        <div style={{ fontSize: 26, color: C.amber, fontWeight: 800, marginBottom: 16 }}>选题卡 · delivery-rating</div>
        {CARD.map(([k, v], i) => {
          const p = prog(f, 6 + i * 4, 18 + i * 4);
          return (
            <div key={k} style={{ display: 'grid', gridTemplateColumns: '210px 1fr', padding: '12px 0', borderBottom: `1px solid ${C.line}`, fontSize: 27,
              opacity: p, transform: `translateX(${(1 - p) * -30}px)` }}>
              <span style={{ color: k === '待定口径' ? C.amber : C.blue, fontWeight: 700 }}>{k}</span>
              <span>{v}</span>
            </div>
          );
        })}
        <div style={{ marginTop: 22, fontFamily: MONO, fontSize: 26, color: C.amber }}>
          确认这个选题吗？ › <span style={{ color: C.green, fontWeight: 800 }}>{answer}</span>
          <span style={{ opacity: Math.floor(f / 8) % 2 ? 1 : 0 }}>▍</span>
        </div>
      </Glass>
      <div style={{ position: 'absolute', left: 1260, top: 640, transform: `rotate(-12deg) scale(${interpolate(stamp, [0, 1], [2.2, 1])})`, opacity: Math.min(1, stamp * 1.4),
        border: `6px solid ${C.green}`, color: C.green, borderRadius: 18, padding: '14px 28px', fontSize: 44, fontWeight: 900, fontFamily: SANS, background: 'rgba(6,10,19,0.85)', letterSpacing: '0.08em' }}>
        ✓ 研究者已确认
      </div>
      <div style={{ position: 'absolute', left: 420, top: 965, fontSize: 26, color: C.sub, opacity: prog(f, 60, 72) }}>未经你确认，助理不会构造任何变量</div>
    </AbsoluteFill>
  );
};

/* ---------- 6. Research definitions: the researcher decides ---------- */
export const Decision: React.FC = () => {
  const f = useCurrentFrame();
  const flip = prog(f, 34, 46);
  const late = interpolate(flip, [0, 1], [6381, 7661]);
  return (
    <AbsoluteFill>
      <Headline kicker="05 · 关键口径" title="会改变结论的定义，你来决定" accent={C.amber} size={60} />
      <div style={{ position: 'absolute', left: 1090, top: 300, width: 720, transform: `perspective(1600px) rotateY(${interpolate(prog(f, 0, 22), [0, 1], [30, 10])}deg)`,
        opacity: prog(f, 0, 18) * 0.95, transformOrigin: 'right center' }}>
        <div style={{ borderRadius: 18, overflow: 'hidden', boxShadow: '0 40px 90px rgba(0,0,0,0.6)', border: `1px solid ${C.line}` }}>
          <Img src={staticFile('asset-decision.png')} style={{ width: 720, display: 'block' }} />
        </div>
        <div style={{ marginTop: 18 }}><Chip color={C.amber}>⏸ 运行在此暂停，证据已导出</Chip></div>
      </div>
      <Glass glow={C.amber} style={{ position: 'absolute', left: 120, top: 320, width: 880, padding: '34px 40px', opacity: prog(f, 6, 20) }}>
        <div style={{ fontSize: 28, color: C.sub }}>「晚到」怎么算？</div>
        <div style={{ position: 'relative', marginTop: 20, height: 84, borderRadius: 42, background: 'rgba(255,255,255,0.06)', border: `1px solid ${C.line}`, display: 'grid', gridTemplateColumns: '1fr 1fr' }}>
          <div style={{ position: 'absolute', top: 6, bottom: 6, left: `calc(${flip * 50}% + 6px)`, width: 'calc(50% - 12px)', borderRadius: 36, background: `linear-gradient(90deg, ${C.amber}, #ff9f43)` }} />
          {['按自然日', '按精确时刻'].map((t, i) => (
            <div key={t} style={{ position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 30, fontWeight: 800,
              color: (i === 0 ? 1 - flip : flip) > 0.5 ? '#1b1206' : C.sub }}>{t}</div>
          ))}
        </div>
        <div style={{ marginTop: 34, fontSize: 26, color: C.sub }}>晚到订单</div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 18 }}>
          <span style={{ fontSize: 110, fontWeight: 900, color: C.text, fontVariantNumeric: 'tabular-nums' }}>{Math.round(late).toLocaleString('en-US')}</span>
          <span style={{ fontSize: 30, color: C.sub }}>/ 95,824 单</span>
        </div>
        <div style={{ height: 16, borderRadius: 8, background: 'rgba(255,255,255,0.06)', overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${(late / 95824) * 100 * 8}%`, background: `linear-gradient(90deg, ${C.amber}, ${C.red})`, borderRadius: 8 }} />
        </div>
        <div style={{ marginTop: 22, opacity: prog(f, 48, 60) }}><Chip color={C.red}>⇄ 1,280 单会因定义不同而换组</Chip></div>
      </Glass>
    </AbsoluteFill>
  );
};

/* ---------- 7. Result, and everything can be traced back ---------- */
export const Result: React.FC = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const q = prog(f, 26, 50);
  return (
    <AbsoluteFill>
      <div style={{ position: 'absolute', left: 120, top: 150, fontFamily: SANS }}>
        <div style={{ fontSize: 30, color: C.sub, opacity: prog(f, 0, 10) }}>平均评分（1–5 分）</div>
        <div style={{ display: 'flex', gap: 70, marginTop: 10 }}>
          {[['准时送达', 4.29, C.green, 0], ['晚于预计', 2.57, C.red, 6]].map(([label, v, color, d]) => {
            const s = pop(f, fps, d as number);
            return (
              <div key={label as string} style={{ transform: `translateY(${(1 - s) * 40}px)`, opacity: s }}>
                <Count to={v as number} start={d as number} dur={22} decimals={2} style={{ fontSize: 170, fontWeight: 900, color: color as string, lineHeight: 1 }} />
                <div style={{ fontSize: 30, color: C.text, marginTop: 8 }}>{label as string}</div>
              </div>
            );
          })}
        </div>
        <div style={{ marginTop: 40, fontSize: 30, color: C.sub, opacity: prog(f, 18, 30), maxWidth: 760, lineHeight: 1.6 }}>
          每个数字背后：SQL、核验、口径选择、来源哈希，<span style={{ color: C.text }}>全部留档，随时可查</span>
        </div>
      </div>
      <div style={{ position: 'absolute', right: 110, top: 160, width: 820, transform: `perspective(1600px) rotateY(${interpolate(q, [0, 1], [-30, -8])}deg) translateY(${(1 - q) * 120}px)`,
        opacity: q, transformOrigin: 'right center' }}>
        <div style={{ borderRadius: 18, overflow: 'hidden', boxShadow: '0 40px 90px rgba(0,0,0,0.6)', border: `1px solid ${C.line}` }}>
          <Img src={staticFile('asset-query.png')} style={{ width: 820, display: 'block' }} />
        </div>
      </div>
      <div style={{ position: 'absolute', left: 120, right: 120, bottom: 70, opacity: prog(f, 36, 54), transform: `translateY(${(1 - prog(f, 36, 54)) * 40}px)` }}>
        <div style={{ borderRadius: 14, overflow: 'hidden', border: `1px solid ${C.line}`, boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
          <Img src={staticFile('asset-pipeline.png')} style={{ width: '100%', display: 'block' }} />
        </div>
      </div>
    </AbsoluteFill>
  );
};

/* ---------- 8. Outro ---------- */
export const Outro: React.FC = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const word = 'Empirical Workbench';
  const cmd = '$ ew chat 我的项目 --raw 原始数据';
  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center', fontFamily: SANS, textAlign: 'center' }}>
      <div style={{ display: 'flex', fontSize: 120, fontWeight: 900, letterSpacing: '-0.01em' }}>
        {Array.from(word).map((ch, i) => {
          const s = pop(f, fps, i * 1.2, 15);
          return (
            <span key={i} style={{ display: 'inline-block', whiteSpace: 'pre', opacity: s, transform: `translateY(${(1 - s) * 60}px) rotate(${(1 - s) * 12}deg)`,
              background: `linear-gradient(180deg, #ffffff, ${i < 9 ? '#bcd3ff' : '#9feaf5'})`, WebkitBackgroundClip: 'text', color: 'transparent' }}>{ch}</span>
          );
        })}
      </div>
      <div style={{ fontSize: 38, color: C.sub, marginTop: 22, opacity: prog(f, 14, 28) }}>和 AI 研究助理一起，把陌生数据变成可核验、可复现的实证数据</div>
      <div style={{ marginTop: 44, fontFamily: MONO, fontSize: 36, padding: '18px 34px', borderRadius: 16, background: 'rgba(17,24,39,0.9)', border: `1px solid ${C.line}`,
        opacity: prog(f, 22, 30), minWidth: 760, textAlign: 'left' }}>
        <span style={{ color: C.cyan }}>{typed(cmd, f, 26, 40)}</span><span style={{ opacity: Math.floor(f / 8) % 2 ? 1 : 0, color: C.text }}>▍</span>
      </div>
      <div style={{ display: 'flex', gap: 16, marginTop: 38, opacity: prog(f, 40, 52) }}>
        <Chip color={C.blue}>本地运行 · DuckDB</Chip>
        <Chip color={C.cyan}>DeepSeek / 任意 OpenAI 兼容模型</Chip>
        <Chip color={C.green}>开源 MIT</Chip>
      </div>
      <div style={{ marginTop: 40, fontSize: 32, color: C.blue, fontFamily: MONO, opacity: prog(f, 48, 60) }}>github.com/xyizhan/empirical-workbench</div>
    </AbsoluteFill>
  );
};

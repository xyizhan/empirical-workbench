import { useEffect, useRef, useState } from 'preact/hooks'
import { api } from './api.js'
import { DataTable, Status, Tabs, fmt, seconds, useTooltip, when } from './common.jsx'

const POLL_MS = 1000

function useRun(id) {
  const [detail, setDetail] = useState(null)
  const [events, setEvents] = useState([])
  const [error, setError] = useState(null)
  const last = useRef(0)

  useEffect(() => {
    let alive = true
    let timer
    last.current = 0
    setDetail(null)
    setEvents([])
    setError(null)
    async function tick() {
      try {
        const [d, fresh] = await Promise.all([api.run(id), api.events(id, last.current)])
        if (!alive) return
        if (fresh.length) {
          last.current = fresh[fresh.length - 1].seq
          setEvents((old) => old.concat(fresh))
        }
        setDetail(d)
        if (!d.run || d.run.status === 'running') timer = setTimeout(tick, POLL_MS)
      } catch (e) {
        if (alive) setError(e.message)
      }
    }
    tick()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [id])
  return { detail, events, error, setDetail }
}

function stageFacts(stage) {
  const checks = stage.attempts.length ? stage.attempts[stage.attempts.length - 1].checks : []
  const parts = []
  if (stage.attempts.length > 1) parts.push(`${stage.attempts.length} 个方案`)
  if (checks.length) parts.push(`${checks.filter((c) => c.passed).length}/${checks.length} 核验`)
  if (stage.exports.length) parts.push(`${stage.exports.length} 个导出`)
  return parts.join(' · ') || (stage.status === 'pending' ? '等待执行' : '无核验')
}

function Pipeline({ stages, selected, onSelect }) {
  return (
    <div class="pipeline" role="list">
      {stages.map((s, i) => (
        <button key={s.name} role="listitem" class="stage-chip" aria-pressed={selected === i} onClick={() => onSelect(i)}>
          <Status value={s.status} />
          <span class="name" title={s.name}>{s.name}</span>
          <span class="facts">{stageFacts(s)}</span>
        </button>
      ))}
    </div>
  )
}

function Check({ check }) {
  const [open, setOpen] = useState(false)
  const mark = check.passed ? ['ok', '✓'] : check.severity === 'warn' ? ['warn', '!'] : ['bad', '×']
  return (
    <div>
      <div class="check">
        <span class={`mark ${mark[0]}`} aria-label={check.passed ? '通过' : check.severity === 'warn' ? '提醒' : '未通过'}>{mark[1]}</span>
        <span>{check.name}</span>
        {!check.passed && (
          <button class="link-btn num" onClick={() => setOpen(!open)}>
            {fmt(check.violations)} 行{check.examples.length ? (open ? ' · 收起样例' : ' · 看样例') : ''}
          </button>
        )}
      </div>
      {open && <div style={{ marginTop: 6 }}><DataTable columns={check.columns} rows={check.examples} max={220} /></div>}
    </div>
  )
}

function ExportPreview({ runId, item }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    setData(null)
    setError(null)
    if (/\.(csv|csv\.gz|parquet)$/i.test(item.file)) api.preview(runId, item.file).then(setData, (e) => setError(e.message))
  }, [runId, item.file])
  return (
    <div class="stack">
      <div class="row spread">
        <span class="muted">共 {fmt(item.rows)} 行 · {item.columns.length} 列{data && item.rows > data.rows.length ? `，预览前 ${data.rows.length} 行` : ''}</span>
        <a href={api.fileUrl(runId, item.file, true)}>下载 {item.file}</a>
      </div>
      {error && <p class="muted">{error}</p>}
      {data ? <DataTable columns={data.columns} rows={data.rows} /> : !error && /\.(csv|gz|parquet)$/i.test(item.file) && <p class="muted">加载中…</p>}
      {!/\.(csv|csv\.gz|parquet)$/i.test(item.file) && <p class="muted">该格式不在页面中预览，请下载查看。</p>}
    </div>
  )
}

function StageDetail({ runId, stage }) {
  const [exportIndex, setExportIndex] = useState(0)
  useEffect(() => setExportIndex(0), [stage.name])
  if (stage.status === 'pending') return <p class="muted">本阶段尚未执行。</p>
  const item = stage.exports[exportIndex]
  return (
    <div class="stack" style={{ gap: 16 }}>
      {stage.description && <p class="secondary" style={{ margin: 0 }}>{stage.description}</p>}
      <section class="stack">
        <h3>处理方案与核验</h3>
        {stage.attempts.length === 0 && <p class="muted">正在执行…</p>}
        {stage.attempts.map((a, i) => (
          <div key={i} class={`item ${a.outcome || ''}`}>
            <div class="row spread">
              <b>{a.plan === 'main' ? '处理' : a.plan}</b>
              <span class="row" style={{ gap: 8 }}>
                {a.outcome === 'accepted' && <span class="status passed"><span class="dot" />采用</span>}
                {a.outcome === 'rejected' && <span class="status failed"><span class="dot" />已回滚</span>}
                {a.duration_s != null && <span class="muted num">{seconds(a.duration_s)}</span>}
              </span>
            </div>
            {a.reason && <pre class="sql-block">{a.reason}</pre>}
            {a.checks.map((c) => <Check key={c.name} check={c} />)}
            {!a.checks.length && a.outcome && <span class="muted">本阶段没有核验。</span>}
          </div>
        ))}
      </section>
      {stage.decision && (
        <section class="stack">
          <h3>研究口径</h3>
          <p style={{ margin: 0 }}>
            {stage.decision.name} = <b>{stage.decision.value ?? '待定'}</b>
            <span class="muted">（{{ default: '配置默认', 'command-line': '启动时指定', interactive: '运行中选择' }[stage.decision.source] || stage.decision.source}）</span>
          </p>
        </section>
      )}
      {stage.tables.length > 0 && (
        <section class="stack">
          <h3>数据表变化</h3>
          <DataTable
            columns={['表', '变化', '行数', '列数']}
            rows={stage.tables.map((t) => [
              t.name,
              { created: '新建', modified: '修改', dropped: '删除' }[t.change],
              t.change === 'modified' ? `${fmt(t.rows_before)} → ${fmt(t.rows)}` : fmt(t.rows ?? t.rows_before),
              t.columns ? t.columns.length : '',
            ])}
            max={260}
          />
        </section>
      )}
      {stage.exports.length > 0 && (
        <section class="stack">
          <h3>导出文件</h3>
          <div class="row" style={{ gap: 6 }}>
            {stage.exports.map((e, i) => (
              <button key={e.file} class="btn" aria-pressed={i === exportIndex} style={i === exportIndex ? { borderColor: 'var(--accent)' } : {}} onClick={() => setExportIndex(i)}>
                {e.file}
              </button>
            ))}
          </div>
          {item && <ExportPreview runId={runId} item={item} />}
        </section>
      )}
    </div>
  )
}

function ScaleChart({ stages }) {
  const tip = useTooltip()
  const groups = stages
    .map((s) => ({ name: s.name, tables: s.tables.filter((t) => t.change !== 'dropped') }))
    .filter((g) => g.tables.length)
  const max = Math.max(1, ...groups.flatMap((g) => g.tables.map((t) => t.rows)))
  if (!groups.length) return <p class="muted">还没有阶段产生数据表。</p>
  return (
    <div class="bars">
      <p class="muted" style={{ margin: 0 }}>每条横条是一个阶段新建或修改的数据表，长度为行数（所有横条共用同一刻度）。</p>
      {groups.map((g) => (
        <div key={g.name} class="bar-group">
          <h3>{g.name}</h3>
          {g.tables.map((t) => (
            <div
              key={t.name}
              class="bar-row"
              onMouseMove={(e) =>
                tip.show(
                  e,
                  <div>
                    <b>{t.name}</b>
                    <div class="num">{fmt(t.rows)} 行 · {t.columns.length} 列</div>
                    {t.change === 'modified' && <div class="num muted">阶段前 {fmt(t.rows_before)} 行</div>}
                    <div class="muted">{g.name}</div>
                  </div>,
                )
              }
              onMouseLeave={tip.hide}
            >
              <span class="label" title={t.name}>{t.name}</span>
              <span class="bar-track"><span class="bar" style={{ width: `${(t.rows / max) * 100}%` }} /></span>
              <span class="value num">{fmt(t.rows)}</span>
            </div>
          ))}
        </div>
      ))}
      {tip.node}
    </div>
  )
}

function QueryPanel({ runId, run }) {
  const tables = [...new Set([...Object.keys(run.sources), ...run.stages.flatMap((s) => s.tables.filter((t) => t.change !== 'dropped').map((t) => t.name))])]
  const [sql, setSql] = useState(() => `select * from ${tables[tables.length - 1] || 'information_schema.tables'} limit 100`)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const ready = run.status !== 'running'
  async function go() {
    setBusy(true)
    setError(null)
    try {
      setResult(await api.query(runId, sql))
    } catch (e) {
      setError(e.message)
      setResult(null)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div class="stack">
      <p class="muted" style={{ margin: 0 }}>在本次运行结束时的工作数据库上执行只读 DuckDB SQL。点击表名填入查询。</p>
      <div class="row" style={{ gap: 6 }}>
        {tables.map((t) => <button key={t} class="pill link-btn" style={{ padding: '1px 8px' }} onClick={() => setSql(`select * from ${t} limit 100`)}>{t}</button>)}
      </div>
      <textarea
        class="sql"
        value={sql}
        onInput={(e) => setSql(e.target.value)}
        onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') go() }}
        aria-label="SQL 查询"
      />
      <div class="row">
        <button class="btn primary" onClick={go} disabled={busy || !ready}>{busy ? '查询中…' : '执行查询'}</button>
        <span class="muted">{ready ? '⌘/Ctrl + Enter 执行 · 最多返回 1,000 行' : '运行结束后可查询'}</span>
      </div>
      {error && <div class="notice critical"><pre>{error}</pre></div>}
      {result && (
        <>
          <span class="muted num">{fmt(result.rows.length)} 行{result.truncated ? '（已截断）' : ''} · {seconds(result.duration_s)}</span>
          <DataTable columns={result.columns} rows={result.rows} />
        </>
      )}
    </div>
  )
}

function EventLog({ events, labels }) {
  const box = useRef(null)
  useEffect(() => {
    if (box.current) box.current.scrollTop = box.current.scrollHeight
  }, [events.length])
  return (
    <div class="log" ref={box}>
      {events.map((e) => (
        <div key={e.seq} class={`log-line ${e.kind.replace('.', '-')}`}>
          <span class="muted num">{e.seq}</span>
          <span class="kind">{labels[e.kind] || e.kind}</span>
          <span class="msg">{e.kind === 'sql' && e.message.length > 240 ? e.message.slice(0, 240) + '…' : e.message}</span>
        </div>
      ))}
      {!events.length && <p class="muted">暂无事件。</p>}
    </div>
  )
}

function DecisionCard({ runId, run, studyId, onRerun }) {
  const stage = run.stages.find((s) => s.status === 'needs_decision')
  const name = stage?.decision?.name
  const spec = name && run.decisions[name]
  const [evidence, setEvidence] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    if (spec?.evidence) api.preview(runId, spec.evidence, 1).then(setEvidence, () => {})
  }, [runId, name])
  if (!spec) return null
  const row = evidence && Object.fromEntries(evidence.columns.map((c, i) => [c, evidence.rows[0]?.[i]]))
  async function choose(option) {
    setError(null)
    try {
      await onRerun({ [name]: option })
    } catch (e) {
      setError(e.message)
    }
  }
  return (
    <div class="notice warning stack">
      <h2>需要研究者确定口径：{name}</h2>
      {spec.default_basis && <p class="secondary" style={{ margin: 0 }}>{spec.default_basis}</p>}
      {row && spec.fields && (
        <dl class="kv" style={{ margin: 0 }}>
          {Object.entries(spec.fields).map(([field, label]) => [<dt key={field + 't'}>{label}</dt>, <dd key={field + 'd'} class="num">{row[field] ?? '—'}</dd>])}
        </dl>
      )}
      {spec.evidence && <span class="muted">证据表：{spec.evidence}（见阶段「{stage.name}」的导出文件）</span>}
      <div class="row">
        {spec.options.map((option) => (
          <button key={option} class="btn primary" onClick={() => choose(option)} disabled={!studyId}>
            采用：{spec.labels?.[option] || option}
          </button>
        ))}
      </div>
      <span class="muted">选择后会以该口径在新目录中重新运行，本次记录保留。</span>
      {!studyId && <span class="muted">该研究不在工作台的研究目录中，无法从页面重跑。</span>}
      {error && <pre>{error}</pre>}
    </div>
  )
}

export function RunView({ id, initialTab, labels, quarto, onStarted }) {
  const { detail, events, error, setDetail } = useRun(id)
  const [selected, setSelected] = useState(null)
  const [tab, setTab] = useState(initialTab || 'stage')
  const [reportBusy, setReportBusy] = useState(false)
  const [reportError, setReportError] = useState(null)
  const run = detail?.run

  useEffect(() => { setSelected(null); setTab(initialTab || 'stage'); setReportError(null) }, [id])
  if (error) return <div class="page"><div class="notice critical"><b>无法读取运行</b><pre>{error}</pre></div></div>
  if (!detail) return <div class="page"><p class="muted">加载中…</p></div>
  if (!run) return <div class="page"><h1>{id}</h1><Status value="running" /><p class="muted">正在启动…</p></div>

  const current = run.stages.findIndex((s) => s.status === 'running' || s.status === 'failed' || s.status === 'needs_decision')
  const index = selected ?? (current >= 0 ? current : run.stages.length - 1)
  const stage = run.stages[index]

  async function rerun(changes) {
    const decisions = {}
    for (const [k, d] of Object.entries(run.decisions)) if (d.source !== 'default' && d.value) decisions[k] = d.value
    Object.assign(decisions, changes)
    const { id: newId } = await api.start({ study: detail.study_id, raw: run.raw, decisions })
    onStarted(newId)
  }

  async function makeReport() {
    setReportBusy(true)
    setReportError(null)
    try {
      setDetail(await api.report(id))
    } catch (e) {
      setReportError(e.message)
    } finally {
      setReportBusy(false)
    }
  }

  return (
    <div class="page">
      <header class="stack" style={{ gap: 6 }}>
        <div class="row spread">
          <Status value={run.status} />
          <div class="row">
            {run.report?.html && <a class="btn" href={api.fileUrl(id, run.report.html)} target="_blank" rel="noopener">打开报告</a>}
            {run.status === 'passed' && (
              <button class="btn" onClick={makeReport} disabled={reportBusy}>
                {reportBusy ? '生成中…' : run.report ? '重新生成报告' : quarto ? '生成报告' : '生成报告源文件'}
              </button>
            )}
            {run.status !== 'running' && detail.study_id && (
              <button class="btn" onClick={() => onStarted(null, { study: detail.study_id, raw: run.raw, decisions: Object.fromEntries(Object.entries(run.decisions).map(([k, d]) => [k, d.value])) })}>
                调整后重跑
              </button>
            )}
          </div>
        </div>
        <h1>{run.study.question || run.study.title}</h1>
        <div class="row muted" style={{ gap: 14 }}>
          <span>{run.study.title}</span>
          {run.study.unit && <span>{run.study.unit}</span>}
          <span>{when(run.started_at)}</span>
          {run.duration_s != null && <span>用时 {seconds(run.duration_s)}</span>}
          {Object.entries(run.decisions).map(([k, d]) => <span key={k} class="pill">{k} = {d.value ?? '待定'}</span>)}
        </div>
        {reportError && <div class="notice critical"><pre>{reportError}</pre></div>}
      </header>

      {run.status === 'needs_decision' && <DecisionCard runId={id} run={run} studyId={detail.study_id} onRerun={rerun} />}
      {(run.status === 'failed' || run.status === 'interrupted') && run.reason && (
        <div class="notice critical"><b>运行未完成</b><pre>{run.reason}</pre></div>
      )}

      <Pipeline stages={run.stages} selected={index} onSelect={(i) => { setSelected(i); setTab('stage') }} />

      <div class="card stack">
        <Tabs
          tabs={[['stage', `阶段 · ${stage.name}`], ['scale', '数据规模'], ['sources', '来源与工具'], ['query', '查询'], ['log', `事件 ${events.length}`]]}
          value={tab}
          onChange={setTab}
        />
        {tab === 'stage' && <StageDetail runId={id} stage={stage} />}
        {tab === 'scale' && <ScaleChart stages={run.stages} />}
        {tab === 'sources' && (
          <div class="stack">
            <DataTable
              columns={['表', '文件', '行数', '列数', '编码', 'SHA-256']}
              rows={Object.entries(run.sources).map(([k, s]) => [k, s.file, fmt(s.rows), s.columns.length, s.encoding || '', s.sha256.slice(0, 16) + '…'])}
              max={260}
            />
            <span class="muted">原始数据目录：{run.raw}</span>
            {run.tools.map((t) => (
              <div key={t.name} class={`item ${t.returncode === 0 ? 'accepted' : t.returncode == null ? '' : 'rejected'}`}>
                <div class="row spread">
                  <b>{t.label}</b>
                  <a href={api.fileUrl(id, t.log)} target="_blank" rel="noopener">{t.log}</a>
                </div>
                <code class="muted" style={{ overflowWrap: 'anywhere' }}>{t.argv.join(' ')}</code>
              </div>
            ))}
          </div>
        )}
        {tab === 'query' && <QueryPanel runId={id} run={run} />}
        {tab === 'log' && <EventLog events={events} labels={labels} />}
      </div>
    </div>
  )
}

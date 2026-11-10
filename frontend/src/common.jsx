import { useState } from 'preact/hooks'

export const STATUS = {
  passed: '已通过',
  failed: '失败',
  needs_decision: '待研究者决定',
  interrupted: '已中断',
  running: '运行中',
  pending: '未开始',
}

export function Status({ value }) {
  return (
    <span class={`status ${value}`}>
      <span class="dot" aria-hidden="true" />
      {STATUS[value] || value}
    </span>
  )
}

export const fmt = (n) => (n == null ? '—' : Number(n).toLocaleString('zh-CN'))

export function when(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (x) => String(x).padStart(2, '0')
  return `${d.getMonth() + 1}月${d.getDate()}日 ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export const seconds = (s) => (s == null ? '' : s < 60 ? `${s.toFixed(1)} 秒` : `${Math.floor(s / 60)} 分 ${Math.round(s % 60)} 秒`)

const isNumeric = (v) => typeof v === 'number' || (typeof v === 'string' && /^-?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?( → -?(\d{1,3}(,\d{3})+|\d+))?$/.test(v) && !/^0\d/.test(v))

export function DataTable({ columns, rows, max = 460 }) {
  if (!columns?.length) return <p class="muted">没有返回列。</p>
  // A column is right-aligned when every non-missing value in it is a number.
  const numeric = columns.map((_, j) => rows.some((r) => r[j] != null && r[j] !== '') && rows.every((r) => r[j] == null || r[j] === '' || isNumeric(r[j])))
  return (
    <div class="table-wrap" style={{ maxHeight: max }}>
      <table class="data">
        <thead>
          <tr>{columns.map((c, j) => <th key={c} title={c} class={numeric[j] ? 'n' : ''}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {row.map((v, j) =>
                v === null || v === '' ? (
                  <td key={j} class="null">缺失</td>
                ) : (
                  <td key={j} class={numeric[j] ? 'n' : ''} title={String(v)}>{String(v)}</td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <div class="tabs" role="tablist">
      {tabs.map(([key, label]) => (
        <button key={key} class="tab" role="tab" aria-selected={value === key} onClick={() => onChange(key)}>
          {label}
        </button>
      ))}
    </div>
  )
}

export function useTooltip() {
  const [tip, setTip] = useState(null)
  const show = (event, content) => setTip({ x: event.clientX, y: event.clientY, content })
  const hide = () => setTip(null)
  const node = tip && (
    <div class="tooltip" style={{ left: Math.min(tip.x + 14, window.innerWidth - 290), top: tip.y + 14 }}>
      {tip.content}
    </div>
  )
  return { show, hide, node }
}

import { useEffect, useState } from 'preact/hooks'
import { api } from './api.js'
import { Status, when } from './common.jsx'
import { NewRun } from './new-run.jsx'
import { RunView } from './run-view.jsx'

function useHash() {
  const [hash, setHash] = useState(location.hash)
  useEffect(() => {
    const on = () => setHash(location.hash)
    addEventListener('hashchange', on)
    return () => removeEventListener('hashchange', on)
  }, [])
  return hash
}

export function App() {
  const hash = useHash()
  const [meta, setMeta] = useState(null)
  const [studies, setStudies] = useState([])
  const [runs, setRuns] = useState([])
  const [preset, setPreset] = useState(null)
  const [error, setError] = useState(null)

  const refreshRuns = () => api.runs().then(setRuns, (e) => setError(e.message))
  useEffect(() => {
    api.meta().then(setMeta, (e) => setError(e.message))
    api.studies().then(setStudies, (e) => setError(e.message))
    refreshRuns()
    const timer = setInterval(refreshRuns, 3000)
    return () => clearInterval(timer)
  }, [])

  const [runPart, tabPart] = hash.startsWith('#/run/') ? hash.slice(6).split('/') : []
  const runId = runPart ? decodeURIComponent(runPart) : null
  useEffect(() => {
    if (!hash && runs.length) location.hash = `#/run/${encodeURIComponent(runs[0].id)}`
    else if (!hash && meta && !runs.length) location.hash = '#/new'
  }, [hash, runs.length, meta])

  function started(id, nextPreset) {
    if (id) {
      setPreset(null)
      refreshRuns()
      location.hash = `#/run/${encodeURIComponent(id)}`
    } else {
      setPreset(nextPreset)
      location.hash = '#/new'
    }
  }

  return (
    <div class="shell">
      <aside class="sidebar">
        <div class="brand">
          <b>EMPIRICAL WORKBENCH</b>
          {meta && <span class="muted" style={{ fontSize: 12 }}>v{meta.version}</span>}
        </div>
        <div class="actions">
          <button class="btn primary block" onClick={() => started(null, null)}>＋ 新建运行</button>
        </div>
        <nav class="run-list" aria-label="运行记录">
          {runs.map((r) => (
            <button key={r.id} class="run-item" aria-current={r.id === runId} onClick={() => (location.hash = `#/run/${encodeURIComponent(r.id)}`)}>
              <div class="title" title={r.title}>{r.title}</div>
              <div class="sub">
                <Status value={r.status} />
                <span>{when(r.started_at)}</span>
                {Object.entries(r.decisions || {}).map(([k, v]) => <span key={k}>{k}={v ?? '待定'}</span>)}
              </div>
            </button>
          ))}
          {!runs.length && <p class="muted" style={{ padding: '0 8px' }}>还没有运行记录。</p>}
        </nav>
        {meta && <div class="muted" title={meta.runs} style={{ padding: '10px 16px', fontSize: 11.5, borderTop: '1px solid var(--border)', overflowWrap: 'anywhere' }}>运行目录 …/{meta.runs.split(/[\\/]/).slice(-2).join('/')}</div>}
      </aside>
      <main class="main">
        {error && <div class="page"><div class="notice critical"><b>工作台出错</b><pre>{error}</pre></div></div>}
        {hash === '#/new' && <NewRun studies={studies} preset={preset} onStarted={started} />}
        {runId && <RunView id={runId} initialTab={tabPart} labels={meta?.events || {}} quarto={meta?.quarto} onStarted={started} />}
      </main>
    </div>
  )
}

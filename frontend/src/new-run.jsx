import { useEffect, useState } from 'preact/hooks'
import { api } from './api.js'

const ASK = '__ask__'

function remembered(key, fallback) {
  try {
    return localStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}

function remember(key, value) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* storage unavailable: nothing to remember */
  }
}

export function NewRun({ studies, preset, onStarted }) {
  const usable = studies.filter((s) => !s.error)
  const [studyId, setStudyId] = useState(preset?.study || usable[0]?.id || '')
  const study = studies.find((s) => s.id === studyId)

  useEffect(() => {
    if (!studyId && usable.length) setStudyId(preset?.study || usable[0].id)
  }, [usable.length])
  const [raw, setRaw] = useState('')
  const [choices, setChoices] = useState({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!study) return
    setRaw(preset?.study === study.id && preset.raw ? preset.raw : remembered(`ew.raw.${study.id}`, study.id === 'panel' ? 'studies/panel' : ''))
    const initial = {}
    for (const [name, d] of Object.entries(study.decisions || {})) {
      initial[name] = preset?.study === study.id && preset.decisions?.[name] != null ? preset.decisions[name] : d.value ?? ASK
    }
    setChoices(initial)
  }, [studyId, studies.length])

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    remember(`ew.raw.${studyId}`, raw)
    // Send only what differs from the study's default, so the run records the source honestly.
    const decisions = Object.fromEntries(
      Object.entries(choices)
        .filter(([k, v]) => v === ASK || v !== study.decisions[k].value)
        .map(([k, v]) => [k, v === ASK ? '' : v]),
    )
    try {
      const { id } = await api.start({ study: studyId, raw, decisions })
      onStarted(id)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (!studies.length) return <div class="page"><div class="card empty">研究目录中没有 study.json。</div></div>

  return (
    <div class="page">
      <h1>新建运行</h1>
      <form class="card stack" onSubmit={submit}>
        <label class="field">
          <span>研究</span>
          <select value={studyId} onChange={(e) => setStudyId(e.target.value)}>
            {studies.map((s) => (
              <option key={s.id} value={s.id} disabled={!!s.error}>
                {s.title}{s.error ? '（配置有误）' : ''}
              </option>
            ))}
          </select>
        </label>
        {study?.question && <p class="secondary" style={{ margin: 0 }}>{study.question}</p>}
        {study?.error && <div class="notice critical"><pre>{study.error}</pre></div>}
        <label class="field">
          <span>原始数据目录</span>
          <input type="text" value={raw} onInput={(e) => setRaw(e.target.value)} placeholder="例如 ../data/raw（相对于启动 ew serve 的目录）" required />
        </label>
        {Object.entries(study?.decisions || {}).map(([name, d]) => (
          <fieldset key={name} class="field" style={{ border: 'none', padding: 0, margin: 0 }}>
            <span>研究口径 · {name}</span>
            {d.basis && <small class="muted">{d.basis}</small>}
            <div class="stack" style={{ gap: 6 }}>
              {d.options.map((option) => (
                <label key={option} class="choice">
                  <input type="radio" name={name} checked={choices[name] === option} onChange={() => setChoices({ ...choices, [name]: option })} />
                  <span>
                    {d.labels?.[option] || option} <code class="muted">{option}</code>
                    {d.value === option && <span class="pill" style={{ marginLeft: 6 }}>配置默认</span>}
                  </span>
                </label>
              ))}
              <label class="choice">
                <input type="radio" name={name} checked={choices[name] === ASK} onChange={() => setChoices({ ...choices, [name]: ASK })} />
                <span>运行到这里先暂停，看过证据再决定</span>
              </label>
            </div>
          </fieldset>
        ))}
        {error && <div class="notice critical"><b>无法开始运行</b><pre>{error}</pre></div>}
        <div class="row">
          <button class="btn primary" type="submit" disabled={busy || !study || study.error}>{busy ? '正在启动…' : '开始运行'}</button>
          <span class="muted">每次运行写入新的目录，原有结果不会被覆盖。</span>
        </div>
      </form>
    </div>
  )
}

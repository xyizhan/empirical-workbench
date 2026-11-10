async function request(path, options = {}) {
  const response = await fetch('api/' + path, options)
  const body = await response.json().catch(() => ({ error: `HTTP ${response.status}` }))
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`)
  return body
}

const post = (path, body) =>
  request(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

const enc = encodeURIComponent

export const api = {
  meta: () => request('meta'),
  studies: () => request('studies'),
  runs: () => request('runs'),
  run: (id) => request(`runs/${enc(id)}`),
  events: (id, after) => request(`runs/${enc(id)}/events?after=${after}`),
  preview: (id, file, limit = 200) => request(`runs/${enc(id)}/preview/${enc(file)}?limit=${limit}`),
  fileUrl: (id, file, download = false) => `api/runs/${enc(id)}/files/${enc(file)}${download ? '?download=1' : ''}`,
  start: (body) => post('runs', body),
  query: (id, sql) => post(`runs/${enc(id)}/query`, { sql }),
  report: (id) => post(`runs/${enc(id)}/report`, {}),
}

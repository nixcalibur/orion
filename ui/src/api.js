const API_URL = import.meta.env.VITE_API_URL || '/api'
const API_KEY = import.meta.env.VITE_API_KEY || ''

function headers() {
  const h = {}
  if (API_KEY) h['X-API-Key'] = API_KEY
  return h
}

export async function listAssessments() {
  const res = await fetch(`${API_URL}/assessments`, { headers: headers() })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getAssessment(id) {
  const res = await fetch(`${API_URL}/assessments/${id}`, { headers: headers() })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function submitReview(id, review) {
  const res = await fetch(`${API_URL}/assessments/${id}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers() },
    body: JSON.stringify(review),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function uploadAssessment(formData) {
  const res = await fetch(`${API_URL}/assessments`, {
    method: 'POST',
    body: formData,
    headers: headers(),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function startFromPath(path) {
  const body = new FormData()
  body.append('path', path)
  return uploadAssessment(body)
}

export async function checkHealth() {
  const res = await fetch(`${API_URL}/health`)
  if (!res.ok) throw new Error('API health check failed')
  return res.json()
}

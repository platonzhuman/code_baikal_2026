import { getRole, getSessionId, getToken } from './auth'

const MOCK = {
  status: 'success',
  text: 'Сервер не отвечает. Это демо-строка, не данные из базы.',
  sql: 'SELECT 1',
  result: {
    columns: ['demo'],
    rows: [{ demo: 'ok' }],
    row_count: 1,
  },
}

export async function sendChat(question) {
  const payload = {
    question,
    role: getRole(), // роль отправляем для гостя; сервер предпочитает токен
    session_id: getSessionId(),
    explain: true,
    max_rows: 50,
  }

  const headers = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`

  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
    })
    const data = await res.json().catch(() => null)
    if (res.status === 401) {
      return { status: 'error', error: { message: 'Сессия истекла. Войдите снова.' } }
    }
    if (res.status === 429) {
      return { status: 'error', error: { message: 'Слишком много запросов. Подождите минуту.' } }
    }
    if (!data || (data.status !== 'success' && data.status !== 'error')) {
      return { status: 'error', error: { message: 'Сервер вернул не ответ чата.' } }
    }
    return data
  } catch {
    return MOCK
  }
}

export async function fetchLogs() {
  const res = await fetch('/logs')
  const data = await res.json()
  return Array.isArray(data) ? data : data.items || []
}

export async function fetchAnalytics() {
  const res = await fetch('/analytics')
  if (!res.ok) throw new Error('analytics')
  return res.json()
}

import { getRole, getSessionId } from './auth'

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
    role: getRole(),
    session_id: getSessionId(),
    explain: true,
    max_rows: 50,
  }

  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    const data = await res.json().catch(() => null)
    if (!data || (data.status !== 'success' && data.status !== 'error')) {
      return {
        status: 'error',
        error: { message: 'Сервер вернул не ответ чата.' },
      }
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

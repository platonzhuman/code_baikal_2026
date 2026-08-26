const TOKEN_KEY = 'gigachads_token'
const ROLE_KEY = 'gigachads_role'
const SESSION_KEY = 'gigachads_session_id'

const ROLE_LABEL = {
  applicant: 'Абитуриент',
  student: 'Студент',
  teacher: 'Преподаватель',
  staff: 'Сотрудник',
}

export function isLoggedIn() {
  return Boolean(localStorage.getItem(TOKEN_KEY))
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function getRole() {
  return localStorage.getItem(ROLE_KEY) || 'applicant'
}

export function getRoleLabel() {
  return ROLE_LABEL[getRole()] || 'Абитуриент'
}

export async function login(login, password) {
  const res = await fetch('/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login, password }),
  })
  if (!res.ok) {
    const d = await res.json().catch(() => null)
    throw new Error(d?.detail || d?.message || 'Неверный логин или пароль')
  }
  const data = await res.json()
  localStorage.setItem(TOKEN_KEY, data.token)
  localStorage.setItem(ROLE_KEY, data.role)
  return data
}

export function logout() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(ROLE_KEY)
}

export function getSessionId() {
  let id = sessionStorage.getItem(SESSION_KEY)
  if (!id) {
    id = crypto.randomUUID()
    sessionStorage.setItem(SESSION_KEY, id)
  }
  return id
}

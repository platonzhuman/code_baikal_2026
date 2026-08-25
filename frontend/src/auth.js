const AUTH_KEY = 'gigachads_logged_in'
const SESSION_KEY = 'gigachads_session_id'

export function isLoggedIn() {
  return localStorage.getItem(AUTH_KEY) === '1'
}

export function login() {
  localStorage.setItem(AUTH_KEY, '1')
}

export function logout() {
  localStorage.removeItem(AUTH_KEY)
}

export function getRole() {
  return isLoggedIn() ? 'staff' : 'applicant'
}

export function getSessionId() {
  let id = sessionStorage.getItem(SESSION_KEY)
  if (!id) {
    id = crypto.randomUUID()
    sessionStorage.setItem(SESSION_KEY, id)
  }
  return id
}

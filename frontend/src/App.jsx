import { useState } from 'react'
import Chat from './components/Chat'
import Analytics from './components/Analytics'
import Welcome from './components/Welcome'
import { isLoggedIn, login, logout, getRoleLabel } from './auth'

const embed = new URLSearchParams(window.location.search).has('embed')

// Общие учётки на роль (совпадают с backend/.env): login/password
const ACCOUNTS = [
  { role: 'student', label: 'Студент', login: 'student', password: 'student' },
  { role: 'teacher', label: 'Преподаватель', login: 'teacher', password: 'teacher' },
  { role: 'staff', label: 'Сотрудник', login: 'staff', password: 'staff' },
]

export default function App() {
  const [page, setPage] = useState(embed ? 'chat' : 'welcome')
  const [loggedIn, setLoggedIn] = useState(isLoggedIn())
  const [loading, setLoading] = useState(false)
  const [authError, setAuthError] = useState('')

  async function doLogin(e) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    const loginValue = String(form.get('login') || '').trim()
    const pass = String(form.get('password') || '')
    setLoading(true)
    setAuthError('')
    try {
      await login(loginValue, pass)
      setLoggedIn(true)
      setPage('chat')
    } catch (err) {
      setAuthError(err.message || 'Не удалось войти')
    } finally {
      setLoading(false)
    }
  }

  function quickLogin(account) {
    // заполняем и сразу отправляем вход от имени роли
    const form = document.querySelector('form.login')
    if (!form) return
    form.login.value = account.login
    form.password.value = account.password
    form.requestSubmit()
  }

  function doLogout() {
    logout()
    setLoggedIn(false)
    setAuthError('')
    setPage('welcome')
  }

  return (
    <div className="app" data-page={page} data-embed={embed ? '1' : undefined}>
      {embed ? (
        <div className="bg-media bg-still" aria-hidden="true" />
      ) : (
        <video className="bg-media" autoPlay muted loop playsInline poster="/bg.jpg">
          <source src="/bg.mp4" type="video/mp4" />
        </video>
      )}
      {!embed && (
        <header>
          <div className="hud glass">
            <button type="button" className="logo" onClick={() => { setPage('welcome'); window.scrollTo(0, 0) }}>
              G
            </button>
            {page !== 'login' && (
              <nav>
                <button type="button" className={page === 'chat' ? 'on' : ''} onClick={() => setPage('chat')}>
                  Чат
                </button>
                {loggedIn && (
                  <button type="button" className={page === 'analytics' ? 'on' : ''} onClick={() => setPage('analytics')}>
                    Аналитика
                  </button>
                )}
              </nav>
            )}
          </div>
          <div className="hud hud-auth glass">
            {page !== 'login' && <span className="badge">{loggedIn ? getRoleLabel() : 'Абитуриент'}</span>}
            {page === 'login' ? (
              <button type="button" className="ghost" onClick={() => setPage('welcome')}>Отмена</button>
            ) : loggedIn ? (
              <button type="button" className="ghost" onClick={doLogout}>Выйти</button>
            ) : (
              <button type="button" className="ghost" onClick={() => setPage('login')}>Войти</button>
            )}
          </div>
        </header>
      )}
      <main>
        {page === 'welcome' && (
          <Welcome
            onChat={() => setPage('chat')}
            loggedIn={loggedIn}
            onLogin={() => setPage('login')}
            onLogout={doLogout}
          />
        )}
        {page === 'chat' && <Chat />}
        {page === 'analytics' && <Analytics />}
        {page === 'login' && (
          <form className="login glass" onSubmit={doLogin}>
            <p className="kicker">Вход по роли</p>
            <h1>Войти</h1>
            <p>Гость продолжает как абитуриент. Выберите роль или введите логин/пароль.</p>
            <div className="login-roles">
              {ACCOUNTS.map((a) => (
                <button
                  key={a.role}
                  type="button"
                  className="chip"
                  disabled={loading}
                  onClick={() => quickLogin(a)}
                >
                  {a.label}
                </button>
              ))}
            </div>
            <label>
              Логин
              <input name="login" placeholder="student / teacher / staff" autoComplete="username" />
            </label>
            <label>
              Пароль
              <input name="password" type="password" placeholder="Пароль" autoComplete="current-password" />
            </label>
            {authError && <p className="warn">{authError}</p>}
            <button type="submit" className="primary" disabled={loading}>
              {loading ? 'Вход…' : 'Войти'}
            </button>
          </form>
        )}
      </main>
    </div>
  )
}

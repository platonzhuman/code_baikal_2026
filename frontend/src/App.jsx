import { useState } from 'react'
import Chat from './components/Chat'
import Analytics from './components/Analytics'
import Welcome from './components/Welcome'
import { isLoggedIn, login, logout, getRoleLabel } from './auth'

const embed = new URLSearchParams(window.location.search).has('embed')

// Общие учётки на роль (совпадают с backend/.env). Пароль вводит пользователь.
const ACCOUNTS = [
  { role: 'student', label: 'Студент', login: 'student', passwordHint: 'student2026' },
  { role: 'teacher', label: 'Преподаватель', login: 'teacher', passwordHint: 'teacher2026' },
  { role: 'staff', label: 'Сотрудник', login: 'staff', passwordHint: 'admin2026' },
]

export default function App() {
  const [page, setPage] = useState(embed ? 'chat' : 'welcome')
  const [loggedIn, setLoggedIn] = useState(isLoggedIn())
  const [loading, setLoading] = useState(false)
  const [authError, setAuthError] = useState('')
  const [roleLogin, setRoleLogin] = useState('')
  const [password, setPassword] = useState('')

  async function doLogin(e) {
    e.preventDefault()
    if (!roleLogin.trim() || !password) {
      setAuthError('Введите логин и пароль')
      return
    }
    setLoading(true)
    setAuthError('')
    try {
      await login(roleLogin.trim(), password)
      setLoggedIn(true)
      setPage('chat')
    } catch (err) {
      setAuthError(err.message || 'Не удалось войти')
    } finally {
      setLoading(false)
    }
  }

  function chooseRole(account) {
    // подставляем логин + подсказку пароля; пароль вводит пользователь сам
    setRoleLogin(account.login)
    setPassword('')
    setAuthError('')
  }

  function doLogout() {
    logout()
    setLoggedIn(false)
    setAuthError('')
    setRoleLogin('')
    setPassword('')
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
            <p>Гость продолжает как абитуриент. Выберите роль, введите пароль.</p>
            <div className="login-roles">
              {ACCOUNTS.map((a) => (
                <button
                  key={a.role}
                  type="button"
                  className={'chip' + (roleLogin === a.login ? ' on' : '')}
                  disabled={loading}
                  onClick={() => chooseRole(a)}
                >
                  {a.label}
                </button>
              ))}
            </div>
            <label>
              Логин
              <input name="login" value={roleLogin} readOnly placeholder="Выберите роль выше" autoComplete="username" />
            </label>
            <label>
              Пароль
              <input
                name="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={roleLogin ? `пароль (подсказка: ${ACCOUNTS.find(a => a.login === roleLogin)?.passwordHint})` : 'Введите пароль'}
                autoComplete="current-password"
              />
            </label>
            {authError && <p className="warn">{authError}</p>}
            <button type="submit" className="primary" disabled={loading || !roleLogin || !password}>
              {loading ? 'Вход…' : 'Войти'}
            </button>
          </form>
        )}
      </main>
    </div>
  )
}

import { useCallback, useEffect, useState } from 'react'
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

function IntegrationModal({ onClose }) {
  const origin = window.location.origin
  const snippet = `<script src="${origin}/widget.js" async></script>`
  const iframeSnippet = `<iframe
  src="${origin}/?embed=1"
  title="Чат GIGACHADS"
  style="border:0;width:380px;height:560px;border-radius:16px">
</iframe>`
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
    }
    document.body.classList.add('modal-open')
    window.addEventListener('keydown', onKey)
    return () => {
      document.body.classList.remove('modal-open')
      window.removeEventListener('keydown', onKey)
    }
  }, [onClose])

  async function copySnippet() {
    try {
      await navigator.clipboard.writeText(snippet)
    } catch {
      const area = document.createElement('textarea')
      area.value = snippet
      area.setAttribute('readonly', '')
      area.style.position = 'fixed'
      area.style.left = '-9999px'
      document.body.appendChild(area)
      area.select()
      document.execCommand('copy')
      document.body.removeChild(area)
    }
    setCopied(true)
    window.setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div
      className="modal-overlay"
      onClick={onClose}
      onWheel={(e) => e.stopPropagation()}
      role="presentation"
    >
      <div
        className="modal glass"
        role="dialog"
        aria-modal="true"
        aria-labelledby="integrate-title"
        onClick={(e) => e.stopPropagation()}
      >
        <button type="button" className="modal-close" onClick={onClose} aria-label="Закрыть">
          ×
        </button>
        <p className="kicker">Любой сайт</p>
        <h2 id="integrate-title">Интеграция</h2>
        <p>
          Вставьте одну строку в подвал сайта — блок «произвольный HTML», «HTML-код»
          или «скрипты в footer». WordPress, Bitrix, Tilda и любой HTML.
        </p>
        <pre className="snippet"><code>{snippet}</code></pre>
        <button type="button" className="ghost snippet-copy" onClick={copySnippet}>
          {copied ? 'Скопировано' : 'Скопировать код'}
        </button>
        <p>
          Программист не нужен: достаточно HTML-блока в CMS. Справа внизу появится
          кнопка чата. Окно открывается в изолированном iframe и не ломает вёрстку.
        </p>
        <p className="muted">Если скрипты подключить нельзя — рамка на странице:</p>
        <pre className="snippet snippet-iframe"><code>{iframeSnippet}</code></pre>
      </div>
    </div>
  )
}

export default function App() {
  const [page, setPage] = useState(embed ? 'chat' : 'welcome')
  const [loggedIn, setLoggedIn] = useState(isLoggedIn())
  const [loading, setLoading] = useState(false)
  const [authError, setAuthError] = useState('')
  const [roleLogin, setRoleLogin] = useState('')
  const [password, setPassword] = useState('')
  const [showIntegrate, setShowIntegrate] = useState(false)
  const closeIntegrate = useCallback(() => setShowIntegrate(false), [])
  const openIntegrate = useCallback(() => setShowIntegrate(true), [])

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

  const selected = ACCOUNTS.find((a) => a.login === roleLogin)

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
            <button type="button" className="logo" onClick={() => { setPage('welcome'); document.querySelector('.app')?.scrollTo(0, 0) }}>
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
            {page !== 'login' && (
              <button type="button" className="ghost" onClick={openIntegrate}>Интеграция</button>
            )}
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
            onIntegrate={openIntegrate}
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
              <span>Логин</span>
              <input name="login" value={roleLogin} readOnly placeholder="Выберите роль выше" autoComplete="username" />
            </label>
            <label>
              <span>Пароль</span>
              <input
                name="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Введите пароль"
                autoComplete="current-password"
              />
            </label>
            {selected && <p className="login-hint">Демо: {selected.passwordHint}</p>}
            {authError && <p className="warn">{authError}</p>}
            <button type="submit" className="primary" disabled={loading || !roleLogin || !password}>
              {loading ? 'Вход…' : 'Войти'}
            </button>
          </form>
        )}
      </main>
      {showIntegrate && <IntegrationModal onClose={closeIntegrate} />}
    </div>
  )
}

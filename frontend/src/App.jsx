import { useState } from 'react'
import Chat from './components/Chat'
import Analytics from './components/Analytics'
import Welcome from './components/Welcome'
import { isLoggedIn, login, logout } from './auth'

const embed = new URLSearchParams(window.location.search).has('embed')

export default function App() {
  const [page, setPage] = useState(embed ? 'chat' : 'welcome')
  const [loggedIn, setLoggedIn] = useState(isLoggedIn())

  function doLogin(e) {
    e.preventDefault()
    login()
    setLoggedIn(true)
    setPage('chat')
  }

  function doLogout() {
    logout()
    setLoggedIn(false)
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
            {page !== 'login' && <span className="badge">{loggedIn ? 'Сотрудник' : 'Гость'}</span>}
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
            <p className="kicker">Сотрудник</p>
            <h1>Вход</h1>
            <p>Гость продолжает без учётки. Пароль на сервер не уходит.</p>
            <input name="login" placeholder="Логин" autoComplete="username" />
            <input name="password" type="password" placeholder="Пароль" autoComplete="current-password" />
            <button type="submit" className="primary">Войти</button>
          </form>
        )}
      </main>
    </div>
  )
}

import { useEffect, useRef } from 'react'

const OFFER = [
  {
    title: 'Вопрос своими словами',
    text: 'Не надо знать SQL и названия таблиц.',
  },
  {
    title: 'Ответ текстом и таблицей',
    text: 'Можно сразу унести в CSV.',
  },
  {
    title: 'Два уровня доступа',
    text: 'Гость видит открытое, сотрудник после входа — внутренние срезы.',
  },
]

const PRINCIPLES = [
  {
    n: '01',
    title: 'Только факты из базы',
    text: 'Цифры не додумываются.',
  },
  {
    n: '02',
    title: 'Без персональных данных студентов',
    text: 'ФИО, почта, зачётки в ответ не попадают.',
  },
  {
    n: '03',
    title: 'SQL на виду',
    text: 'Можно проверить, что именно ушло в Postgres.',
  },
]

function desktopSmooth() {
  return window.matchMedia('(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)').matches
}

export default function Welcome({ onChat, loggedIn, onLogin, onLogout, onIntegrate }) {
  const rootRef = useRef(null)
  const toTop = useRef(() => window.scrollTo(0, 0))

  useEffect(() => {
    const root = rootRef.current
    if (!root) return
    window.scrollTo(0, 0)

    const nodes = [...root.querySelectorAll('[data-reveal]')]
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    let io
    let fallback
    if (reduce) {
      nodes.forEach((el) => el.classList.add('in'))
    } else {
      io = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) {
            if (!entry.isIntersecting) continue
            entry.target.classList.add('in')
            io.unobserve(entry.target)
          }
        },
        { threshold: 0.18, rootMargin: '0px 0px -6% 0px' },
      )
      nodes.forEach((el) => io.observe(el))
      fallback = setTimeout(() => nodes.forEach((el) => el.classList.add('in')), 1400)
    }

    let current = 0
    let target = 0
    let raf = 0
    const limit = () => Math.max(0, document.documentElement.scrollHeight - window.innerHeight)

    const tick = () => {
      current += (target - current) * 0.16
      if (Math.abs(target - current) < 0.35) {
        current = target
        window.scrollTo(0, current)
        raf = 0
        return
      }
      window.scrollTo(0, current)
      raf = requestAnimationFrame(tick)
    }

    const go = (y) => {
      target = Math.max(0, Math.min(limit(), y))
      if (!raf) raf = requestAnimationFrame(tick)
    }

    toTop.current = () => go(0)

    const onWheel = (e) => {
      if (document.body.classList.contains('modal-open') || !desktopSmooth() || e.ctrlKey) return
      e.preventDefault()
      let dy = e.deltaY
      if (e.deltaMode === 1) dy *= 16
      if (e.deltaMode === 2) dy *= window.innerHeight
      go(target + dy)
    }

    const onScroll = () => {
      if (raf) return
      current = window.scrollY
      target = window.scrollY
    }

    if (desktopSmooth()) {
      window.addEventListener('wheel', onWheel, { passive: false })
      window.addEventListener('scroll', onScroll, { passive: true })
    }

    return () => {
      clearTimeout(fallback)
      io?.disconnect()
      window.removeEventListener('wheel', onWheel)
      window.removeEventListener('scroll', onScroll)
      if (raf) cancelAnimationFrame(raf)
    }
  }, [])

  return (
    <div className="landing" ref={rootRef}>
      <section className="welcome">
        <h1>
          <span className="brand">GIGACHADS</span>
          Данные университета — на человеческом языке
        </h1>
        <p className="slogan">Развеять сомнения помогает только истина.</p>
        <button type="button" className="cta" onClick={onChat}>
          Открыть чат
        </button>
      </section>

      <section className="band">
        <p className="kicker">Продукт</p>
        <h2>Что предлагаем</h2>
        <div className="offer-grid">
          {OFFER.map((item, i) => (
            <article key={item.title} className="offer-card glass" data-reveal={i}>
              <h3>{item.title}</h3>
              <p>{item.text}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="band band-right">
        <p className="kicker">Правила</p>
        <h2>Наши принципы</h2>
        <ol className="principle-list glass">
          {PRINCIPLES.map((item, i) => (
            <li key={item.n} data-reveal={i}>
              <span>{item.n}</span>
              <div>
                <h3>{item.title}</h3>
                <p>{item.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <footer className="site-foot glass">
        <div className="hud glass">
          <button type="button" className="logo" onClick={() => toTop.current()}>
            G
          </button>
          <span className="foot-brand">GIGACHADS</span>
          <span className="foot-meta">Code Baikal 2026</span>
        </div>
        <div className="hud hud-auth glass">
          <button type="button" className="ghost" onClick={onChat}>Открыть чат</button>
          {loggedIn ? (
            <button type="button" className="ghost" onClick={onLogout}>Выйти</button>
          ) : (
            <button type="button" className="ghost" onClick={onLogin}>Войти</button>
          )}
          <button type="button" className="ghost" onClick={onIntegrate}>Интеграция</button>
        </div>
      </footer>
    </div>
  )
}

import { useEffect, useRef } from 'react'

const OFFER = [
  {
    title: 'Вопрос своими словами',
    text: 'Приёмная комиссия не говорит на JOIN. Гость пишет, как человеку — система сама находит таблицы и колонки.',
    items: [
      '«Сколько бюджетных мест» — без схемы и названий полей',
      'Средний балл, факультеты, направления — своими словами',
      'Гость видит только открытое; после входа вопрос идёт в срез роли',
      'Опечатка не ломает запрос: формулировку сопоставляют со схемой',
      'Не надо знать, как таблица называется в Postgres',
    ],
  },
  {
    title: 'Ответ текстом и таблицей',
    text: 'Не чат ради чата: на экране сразу цифра, строки из Postgres и выгрузка. Это можно унести в отчёт, не копируя консоль.',
    items: [
      'Короткий текст: сколько, какой средний, какие факультеты',
      'Таблица — живые агрегаты, не скриншот pgAdmin',
      'CSV одной кнопкой: в Excel, в слайд, в служебную записку',
      'SQL на экране: видно, что именно ушло в базу',
    ],
    table: {
      cols: ['Факультет', 'Мест'],
      rows: [
        ['ИВТ', '120'],
        ['Экономика', '80'],
        ['Юриспруденция', '45'],
      ],
    },
  },
  {
    title: 'Три роли доступа',
    text: 'Это не «гость / админ». После входа роль задаёт, какие таблицы вообще существуют для модели. Чужой срез не подмешивается.',
    items: [
      'Абитуриент: приём, места, баллы, факультеты — как на сайте вуза',
      'Студент: агрегаты потока. Свои и чужие зачётки закрыты',
      'Преподаватель: нагрузка и срезы по дисциплинам, без ПДн группы',
      'Сотрудник: внутренние отчёты. ФИО студентов по-прежнему нельзя',
    ],
  },
  {
    title: 'На сайт вуза за строку',
    text: 'Портал уже есть. Чат не встраивается в вёрстку факультета — он живёт в отдельном окне и не ломает CSS Тильды или Битрикса.',
    items: [
      'Один script в подвал: кнопка сама рисуется справа внизу',
      'Если скрипты на портале закрыты — iframe на отдельный URL',
      'WordPress, Битрикс, Тильда: HTML-блок или footer',
      'Готовый сниппет — кнопка «Интеграция» в шапке и внизу сайта',
    ],
  },
]

const STEPS = [
  {
    n: '01',
    title: 'Вопрос',
    text: 'Пишете по-русски, как у окна приёмной. Имена таблиц и JOIN знать не нужно — формулировку сопоставляют со схемой роли.',
    items: [
      'По-русски, без имён таблиц и полей',
      'Гость видит открытые цифры приёмки: места, баллы, факультеты',
      'После входа вопрос идёт в срез своей роли, не в чужую схему',
      'Опечатка в формулировке не ломает запрос: модель сопоставляет со схемой',
      'Можно спросить «сколько бюджетных», как человеку, а не как DBA',
    ],
  },
  {
    n: '02',
    title: 'SQL',
    text: 'Модель собирает SELECT только из колонок, которые этой роли вообще видны. Цифру «с потолка» запрос не подставит.',
    items: [
      'Пишет только SELECT — без записи и без DDL',
      'Колонки берутся из схемы, доступной роли, не из «всех таблиц вуза»',
      'Нет строки в Postgres — нет ответа, даже если вопрос звучит уверенно',
      'SQL виден до выполнения: можно прочитать, что уйдёт в базу',
      'Цифры не дорисовываются: модель не заполняет пустую выборку',
    ],
  },
  {
    n: '03',
    title: 'Проверка',
    text: 'Замок стоит до Postgres, не после. Нарушение прав — отказ текстом, модель не «додумывает» цифру.',
    items: [
      'Только чтение: INSERT, UPDATE и DDL отсекаются на замке',
      'ПДн закрыты: ФИО, почта, зачётки, телефоны в ответ не попадают',
      'Колонка вне схемы роли — запрос не выполняется',
      'Отказ честный: «нет доступа», а не выдуманная таблица',
      'Проверку можно показать жюри: это правило системы, не обещание в промпте',
    ],
  },
  {
    n: '04',
    title: 'Таблица',
    text: 'На экран попадает только то, что уже прошло замок. Текст, сетка и SQL — три слоя одного факта, не три разных ответа.',
    items: [
      'Текст — краткая сводка по строкам из базы',
      'Сетка — те же агрегаты, сразу в отчёт или в CSV',
      'SQL — тот SELECT, который судья может повторить',
      'Пустой результат тоже честный: «в базе нет строк», без фантазии',
    ],
    table: {
      cols: ['На экране', 'Откуда'],
      rows: [
        ['Текст', 'Строки из Postgres'],
        ['Таблица', 'Агрегаты по роли'],
        ['SQL', 'Уже проверенный SELECT'],
      ],
    },
  },
]

const OFFER_SHOTS = ['/space-camp.jpg', '/space-milky.jpg']

const FLOW_SHOTS = [
  '/space-camp.jpg',
  '/space-lake.jpg',
  '/space-milky.jpg',
  '/space-aurora.jpg',
]

function MiniTable({ cols, rows }) {
  return (
    <table className="flow-mini">
      <thead>
        <tr>
          {cols.map((c) => (
            <th key={c}>{c}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row[0]}>
            {row.map((cell) => (
              <td key={cell}>{cell}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function OfferBlock({ item }) {
  return (
    <>
      <h3>{item.title}</h3>
      <p>{item.text}</p>
      <ul>
        {item.items.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      {item.table && <MiniTable cols={item.table.cols} rows={item.table.rows} />}
    </>
  )
}

function desktopSmooth() {
  return window.matchMedia('(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)').matches
}

export default function Welcome({ onChat, loggedIn, onLogin, onLogout, onIntegrate }) {
  const rootRef = useRef(null)
  const toTop = useRef(() => {
    document.querySelector('.app')?.scrollTo(0, 0)
  })

  useEffect(() => {
    const root = rootRef.current
    if (!root) return
    const scroller = root.closest('.app') || document.documentElement
    scroller.scrollTop = 0

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
        { root: scroller, threshold: 0.18, rootMargin: '0px 0px -6% 0px' },
      )
      nodes.forEach((el) => io.observe(el))
      fallback = setTimeout(() => nodes.forEach((el) => el.classList.add('in')), 1400)
    }

    let current = 0
    let target = 0
    let raf = 0
    const limit = () => Math.max(0, scroller.scrollHeight - scroller.clientHeight)

    const tick = () => {
      current += (target - current) * 0.16
      if (Math.abs(target - current) < 0.35) {
        current = target
        scroller.scrollTop = current
        raf = 0
        return
      }
      scroller.scrollTop = current
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
      current = scroller.scrollTop
      target = scroller.scrollTop
    }

    if (desktopSmooth()) {
      window.addEventListener('wheel', onWheel, { passive: false })
      scroller.addEventListener('scroll', onScroll, { passive: true })
    }

    return () => {
      clearTimeout(fallback)
      io?.disconnect()
      window.removeEventListener('wheel', onWheel)
      scroller.removeEventListener('scroll', onScroll)
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
        <p className="lead">
          Гость спрашивает по-русски — ответ только из Postgres. SQL видно.
          Абитуриент, студент или сотрудник: у каждой роли свой срез, без чужих зачёток.
        </p>
        <button type="button" className="cta" onClick={onChat}>
          Открыть чат
        </button>
      </section>

      <section className="band band-flow">
        <p className="kicker">Цепочка</p>
        <h2>Как это работает</h2>
        <ol className="flow-stair">
          {STEPS.map((item, i) => (
            <li key={item.n} className="flow-col" data-reveal={i}>
              <figure className="flow-shot">
                <img src={FLOW_SHOTS[i]} alt="" />
              </figure>
              <article className="flow-cell glass">
                <span>{item.n}</span>
                <h3>{item.title}</h3>
                {item.text && <p>{item.text}</p>}
                {item.items && (
                  <ul>
                    {item.items.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                )}
                {item.table && <MiniTable cols={item.table.cols} rows={item.table.rows} />}
              </article>
            </li>
          ))}
        </ol>
      </section>

      <section className="band band-offer">
        <p className="kicker">Продукт</p>
        <h2>Что предлагаем</h2>
        <div className="offer-stage">
          <article className="offer-main glass" data-reveal={0}>
            {OFFER.slice(0, 2).map((item, i) => (
              <div key={item.title} className="offer-pane">
                <OfferBlock item={item} />
                <figure className="offer-pane-shot">
                  <img src={OFFER_SHOTS[i]} alt="" />
                </figure>
              </div>
            ))}
          </article>
          {OFFER.slice(2).map((item, i) => (
            <article key={item.title} className="offer-side glass" data-reveal={i + 1}>
              <OfferBlock item={item} />
            </article>
          ))}
        </div>
      </section>

      <footer className="site-foot">
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

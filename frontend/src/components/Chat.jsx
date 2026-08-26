import { useEffect, useRef, useState } from 'react'
import { sendChat } from '../api'
import { maskResult } from '../pii'
import { downloadCsv } from '../csv'
import { loadThreads, saveThreads } from '../threads'
import { isLoggedIn, getSessionId } from '../auth'

const STARTERS = [
  'Какие факультеты есть в университете?',
  'Сколько бюджетных мест в этом году?',
  'Какой средний балл зачисления на бюджет?',
]

function when(ts) {
  if (!ts) return ''
  const min = Math.round((Date.now() - ts) / 60000)
  if (min < 1) return 'сейчас'
  if (min < 60) return `${min} мин`
  const hrs = Math.round(min / 60)
  if (hrs < 24) return `${hrs} ч`
  return new Date(ts).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
}

function explainBlock(explanation) {
  if (!explanation) return null
  const keys = ['tables', 'joins', 'filters', 'aggregates', 'constraints']
  if (!keys.some((k) => explanation[k]?.length)) return null
  const labels = {
    tables: 'таблицы',
    joins: 'JOIN',
    filters: 'фильтры',
    aggregates: 'агрегаты',
    constraints: 'ограничения',
  }
  return (
    <ul className="explain">
      {keys.map((k) => (
        <li key={k}>{labels[k]}: {(explanation[k] || []).join(', ') || '—'}</li>
      ))}
    </ul>
  )
}

function chipLabel(item) {
  if (!item) return ''
  if (typeof item === 'string') return item
  return item.label || item.field || ''
}

function titleFrom(messages) {
  const first = messages.find((m) => m.from === 'user')
  if (!first) return 'Новый чат'
  const line = first.text.replace(/\s+/g, ' ').trim()
  return line.length > 42 ? `${line.slice(0, 42)}…` : line
}

export default function Chat() {
  const [{ threads, currentId }, setStore] = useState(loadThreads)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [listOpen, setListOpen] = useState(() => window.matchMedia('(min-width: 721px)').matches)
  const bottomRef = useRef(null)
  const areaRef = useRef(null)

  const current = threads.find((t) => t.id === currentId)
  const messages = current?.messages || []
  const empty = messages.length === 0 && !loading

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  useEffect(() => {
    const el = areaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(Math.max(el.scrollHeight, 48), 180)}px`
  }, [input])

  // Восстановление после обрыва сети: если последний вопрос юзера уже был обработан
  // на сервере (есть ответ в истории), а в локальном чате ответа нет — догружаем.
  useEffect(() => {
    let alive = true
    async function recover() {
      try {
        const res = await fetch(`/history?session_id=${getSessionId()}`)
        const data = await res.json()
        if (!alive) return
        const items = data.items || []
        const msgs = threads.find((t) => t.id === currentId)?.messages || []
        const lastUser = [...msgs].reverse().find((m) => m.from === 'user')
        if (!lastUser) return
        const done = items.find(
          (it) => (it.question || '').trim() === lastUser.text.trim() && it.answer && it.status === 'success',
        )
        if (!done) return
        const hasReply = msgs.some((m) => m.from === 'assistant' && m.text === done.answer)
        if (!hasReply) {
          setMessages((prev) => [...prev, { from: 'assistant', text: done.answer, sql: done.sql, restored: true }])
        }
      } catch {
        /* офлайн — просто пропускаем */
      }
    }
    recover()
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function persist(next) {
    saveThreads(next)
    setStore(next)
  }

  function setMessages(updater) {
    setStore((prev) => {
      const prevMsgs = prev.threads.find((t) => t.id === prev.currentId)?.messages || []
      const nextMsgs = updater(prevMsgs)
      const id = prev.currentId || crypto.randomUUID()
      const thread = {
        id,
        title: titleFrom(nextMsgs),
        messages: nextMsgs,
        updatedAt: Date.now(),
      }
      const next = {
        currentId: id,
        threads: [thread, ...prev.threads.filter((t) => t.id !== id)],
      }
      saveThreads(next)
      return next
    })
  }

  function closeListIfMobile() {
    if (window.matchMedia('(max-width: 720px)').matches) setListOpen(false)
  }

  function newChat() {
    persist({ currentId: null, threads })
    setInput('')
    closeListIfMobile()
  }

  function openChat(id) {
    persist({ currentId: id, threads })
    closeListIfMobile()
  }

  function removeChat(id) {
    const nextThreads = threads.filter((t) => t.id !== id)
    persist({
      threads: nextThreads,
      currentId: currentId === id ? (nextThreads[0]?.id ?? null) : currentId,
    })
  }

  async function submit(question) {
    const q = question.trim()
    if (!q || loading) return
    setMessages((prev) => [...prev, { from: 'user', text: q }])
    setInput('')
    setLoading(true)
    const data = await sendChat(q)
    if (data.status === 'error') {
      setMessages((prev) => [
        ...prev,
        {
          from: 'assistant',
          text: data.text || data.error?.message || 'Ошибка запроса',
          sql: data.sql || undefined,
        },
      ])
    } else {
      setMessages((prev) => [
        ...prev,
        {
          from: 'assistant',
          text: data.text,
          sql: data.sql,
          result: maskResult(data.result),
          warning: data.result?.warning,
          truncated: data.result?.truncated,
          explanation: data.explanation,
          suggested: data.result?.suggested_filters,
        },
      ])
    }
    setLoading(false)
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit(input)
    }
  }

  return (
    <div className={`chat-layout${listOpen ? ' listed' : ''}`}>
      <aside className={`threads glass${listOpen ? ' open' : ''}`}>
        <p className="threads-label">История</p>
        <div className="threads-bar">
          <button type="button" className="ghost grow" onClick={newChat}>Новый чат</button>
          <button type="button" className="icon-btn" aria-label="Закрыть список" onClick={() => setListOpen(false)}>
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <path fill="currentColor" d="M3.2 3.2 8 8l4.8-4.8.9.9L8.9 8.9l4.8 4.8-.9.9L8 9.8l-4.8 4.8-.9-.9 4.8-4.8-4.8-4.8.9-.9z" />
            </svg>
          </button>
        </div>
        {threads.length === 0 ? (
          <p className="threads-empty">Пока пусто. Первый вопрос станет чатом.</p>
        ) : (
          <ul>
            {threads.map((t) => (
              <li key={t.id} className={t.id === currentId ? 'on' : ''}>
                <button type="button" className="thread-open" onClick={() => openChat(t.id)}>
                  <span className="thread-title">{t.title}</span>
                  <span className="thread-time">{when(t.updatedAt)}</span>
                </button>
                <button type="button" className="thread-del" aria-label="Удалить чат" onClick={() => removeChat(t.id)}>
                  <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                    <path fill="currentColor" d="M6 2h4l.5 1H14v1H2V3h3.5L6 2zm1 4v6H6V6h1zm3 0v6H9V6h1zM3 5h10l-.7 9.1A1 1 0 0 1 11.3 15H4.7a1 1 0 0 1-1-.9L3 5z" />
                  </svg>
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>

      <div className={empty ? 'chat is-empty' : 'chat'}>
        {!listOpen && (
          <button type="button" className="threads-toggle glass" onClick={() => setListOpen(true)}>
            Чаты
          </button>
        )}
        {listOpen && (
          <button type="button" className="threads-scrim" aria-label="Закрыть" onClick={() => setListOpen(false)} />
        )}
        <div className="history">
          {empty && (
            <div className="empty">
              <p className="kicker">Чат</p>
              <h1>Задайте вопрос</h1>
            </div>
          )}
          {messages.map((m, i) => (
            <article key={i} className={`msg ${m.from}${m.from === 'assistant' ? ' glass' : ''}`}>
              <span className="msg-label">{m.from === 'user' ? 'Вы' : 'Ассистент'}</span>
              <p>{m.text}</p>
              {m.restored && <p className="warn">Восстановлено из истории сервера (ответ не дошёл при обрыве).</p>}
              {m.warning && <p className="warn">{m.warning}</p>}
              {!m.warning && m.truncated && <p className="warn">Запрос широкий: показаны первые строки.</p>}
              {m.suggested?.map((item) => {
                const label = chipLabel(item)
                if (!label) return null
                return (
                  <button
                    key={label}
                    type="button"
                    className="chip"
                    onClick={() => setInput((prev) => (prev ? `${prev} · ${label}` : `Уточни: ${label}`))}
                  >
                    {label}
                  </button>
                )
              })}
              {m.result?.rows?.length > 0 && (
                <div className="result">
                  <div className="result-bar">
                    <span>{m.result.row_count ?? m.result.rows.length} строк</span>
                    <button type="button" className="ghost" onClick={() => downloadCsv(m.result)}>CSV</button>
                  </div>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>{m.result.columns.map((c) => <th key={c}>{c}</th>)}</tr>
                      </thead>
                      <tbody>
                        {m.result.rows.map((row, ri) => (
                          <tr key={ri}>
                            {m.result.columns.map((c) => <td key={c}>{String(row[c])}</td>)}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
              {m.sql && (
                <div className="sql">
                  <span>SQL</span>
                  <pre>{m.sql}</pre>
                </div>
              )}
              {explainBlock(m.explanation)}
            </article>
          ))}
          {loading && (
            <article className="msg assistant glass">
              <span className="msg-label">Ассистент</span>
              <p className="spinner">Готовлю ответ<span>.</span><span>.</span><span>.</span></p>
            </article>
          )}
          <div ref={bottomRef} />
        </div>

        {!isLoggedIn() && (
          <div className="starters">
            {STARTERS.map((q) => (
              <button
                key={q}
                type="button"
                className="starter"
                disabled={loading}
                onClick={() => submit(q)}
              >
                {q}
              </button>
            ))}
          </div>
        )}

        <form
          className="composer glass"
          onSubmit={(e) => {
            e.preventDefault()
            submit(input)
          }}
          onPointerDown={(e) => {
            if (e.target.closest('button')) return
            areaRef.current?.focus()
          }}
        >
          <textarea
            ref={areaRef}
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Вопрос о данных университета"
            disabled={loading}
          />
          <div className="composer-bar">
            <span className="hint">Enter — отправить · Shift+Enter — строка</span>
            <button type="submit" className="send" disabled={loading || !input.trim()} aria-label="Отправить">
              ↑
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

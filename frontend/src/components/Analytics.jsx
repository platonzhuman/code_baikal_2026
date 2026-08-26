import { useEffect, useState } from 'react'
import { fetchAnalytics, fetchLogs } from '../api'
import { downloadCsv } from '../csv'

const PREVIEW = 5

const COLS = [
  ['created_at', 'Время'],
  ['role', 'Роль'],
  ['status', 'Статус'],
  ['question', 'Вопрос'],
  ['latency_ms', 'мс'],
  ['error', 'Ошибка'],
]

const ROLES = [
  { id: 'applicant', label: 'Гость' },
  { id: 'student', label: 'Студент' },
  { id: 'teacher', label: 'Преподаватель' },
  { id: 'staff', label: 'Сотрудник' },
]

const ROLE_LABEL = Object.fromEntries(ROLES.map((r) => [r.id, r.label]))

function formatCell(key, value) {
  if (value == null || value === '') return '—'
  if (key === 'created_at' && typeof value === 'number') {
    return new Date(value * 1000).toLocaleString('ru-RU', {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    })
  }
  if (key === 'role') return ROLE_LABEL[value] || value
  if (key === 'status') {
    if (value === 'success') return 'успех'
    if (value === 'error') return 'отказ'
  }
  return String(value)
}

function pct(part, total) {
  if (!total) return 0
  return Math.round((part / total) * 1000) / 10
}

function fmtPct(n) {
  return `${Number(n || 0).toLocaleString('ru-RU', { maximumFractionDigits: 1 })}%`
}

function fmtMs(n) {
  if (n == null || n === 0) return '—'
  return `${Math.round(n).toLocaleString('ru-RU')} мс`
}

function refusalKind(code) {
  const s = String(code || '').toLowerCase()
  if (s.includes('pdn') || s.includes('пдн') || s.includes('персональн') || s.includes('фио')) {
    return 'pdn'
  }
  if (
    s.includes('read_only') ||
    s.includes('not_select') ||
    s.includes('чтени') ||
    s.includes('изменен') ||
    s.includes('удален')
  ) {
    return 'mutation'
  }
  return 'other'
}

function securityBuckets(refusals) {
  const buckets = { pdn: 0, mutation: 0, other: [] }
  for (const row of refusals || []) {
    const kind = refusalKind(row.code)
    if (kind === 'other') buckets.other.push(row)
    else buckets[kind] += row.count || 0
  }
  return buckets
}

function BarList({ items, empty, value, max, label, meta, tone }) {
  if (!items?.length) return <p className="muted dash-empty">{empty}</p>
  const peak = Math.max(1, max || Math.max(0, ...items.map(value)))
  return (
    <ul className={'dash-bars' + (tone ? ` dash-bars-${tone}` : '')}>
      {items.map((item, i) => (
        <li key={i}>
          <div className="dash-bar-head">
            <span>{label(item)}</span>
            <b>{meta(item)}</b>
          </div>
          <div className="dash-bar-track" aria-hidden="true">
            <i style={{ width: `${(value(item) / peak) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  )
}

export default function Analytics() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [rows, setRows] = useState(null)
  const [logError, setLogError] = useState('')
  const [journal, setJournal] = useState(false)
  const [open, setOpen] = useState(false)
  const [logBusy, setLogBusy] = useState(false)

  useEffect(() => {
    fetchAnalytics()
      .then(setData)
      .catch(() => setError('Сводка запросов пока недоступна.'))
  }, [])

  async function loadLogs() {
    if (rows) return rows
    setLogBusy(true)
    try {
      const list = await fetchLogs()
      setRows(list)
      setLogError('')
      return list
    } catch {
      setLogError('Журнал запросов пока недоступен.')
      return []
    } finally {
      setLogBusy(false)
    }
  }

  async function showJournal() {
    await loadLogs()
    setJournal(true)
  }

  async function exportCsv() {
    const list = await loadLogs()
    if (!list.length) return
    const cols = COLS.filter(([key]) => Object.hasOwn(list[0], key))
    downloadCsv(
      {
        columns: cols.map(([, label]) => label),
        rows: list.map((row) =>
          Object.fromEntries(cols.map(([key, label]) => [label, formatCell(key, row[key])])),
        ),
      },
      'query-log.csv',
    )
  }

  const total = data?.total_queries || 0
  const metrics = data?.metrics || {}
  const success = metrics.success || 0
  const errors = metrics.errors || 0
  const successRate = pct(success, total)
  const refusalRate = metrics.refusal_rate ?? pct(errors, total)
  const p95 = metrics.latency?.p95_ms
  const byRole = metrics.by_role || {}
  const roleItems = ROLES.map((r) => ({
    ...r,
    count: byRole[r.id] || 0,
    share: pct(byRole[r.id] || 0, total),
  }))
  const extraRoles = Object.keys(byRole).filter((id) => !ROLE_LABEL[id])
  const allRoles = [
    ...roleItems,
    ...extraRoles.map((id) => ({
      id,
      label: id,
      count: byRole[id],
      share: pct(byRole[id], total),
    })),
  ]
  const categories = metrics.by_category || []
  const top = data?.top_questions || []
  const recent = data?.recent_queries || []
  const security = securityBuckets(data?.refusals)
  const cols = rows?.length ? COLS.filter(([key]) => Object.hasOwn(rows[0], key)) : []
  const shown = rows && !open && rows.length > PREVIEW ? rows.slice(0, PREVIEW) : rows
  const extra = (rows?.length || 0) > PREVIEW

  return (
    <section className="sheet glass analytics-sheet">
      <p className="kicker">Сводка</p>
      <h1>Аналитика запросов</h1>
      {error && <p className="muted">{error}</p>}
      {!error && !data && <p className="muted">Загрузка…</p>}
      {data && (
        <>
          <div className="dash-kpis">
            <article className="dash-kpi">
              <span>Всего запросов</span>
              <strong>{total.toLocaleString('ru-RU')}</strong>
            </article>
            <article className="dash-kpi">
              <span>% успешных</span>
              <strong>{fmtPct(successRate)}</strong>
              <em>{success.toLocaleString('ru-RU')} из {total.toLocaleString('ru-RU')}</em>
            </article>
            <article className="dash-kpi">
              <span>% отказов</span>
              <strong>{fmtPct(refusalRate)}</strong>
              <em>{errors.toLocaleString('ru-RU')} отказов</em>
            </article>
            <article className="dash-kpi">
              <span>p95</span>
              <strong>{fmtMs(p95)}</strong>
              <em>хвост латентности</em>
            </article>
          </div>

          <div className="dash-grid">
            <article className="dash-card">
              <h2>Топ-10 запросов</h2>
              <BarList
                items={top}
                empty="Пока нет повторяющихся вопросов."
                value={(q) => q.count}
                label={(q) => q.question}
                meta={(q) => `${q.count} · ${fmtPct(q.success_rate)} успеха`}
              />
            </article>
            <article className="dash-card">
              <h2>По категориям</h2>
              <BarList
                items={categories}
                empty="Категорий пока нет."
                value={(c) => c.share}
                max={100}
                label={(c) => c.category}
                meta={(c) => `${c.count} · ${fmtPct(c.share)}`}
              />
            </article>
          </div>

          <div className="dash-grid dash-grid-roles">
            <article className="dash-card">
              <h2>По ролям</h2>
              <BarList
                items={allRoles}
                empty="Ролей пока нет."
                value={(r) => r.count}
                label={(r) => r.label}
                meta={(r) => `${r.count} · ${fmtPct(r.share)}`}
              />
            </article>
            <article className="dash-card dash-card-ok">
              <h2>Безопасность</h2>
              <p className="dash-ok-lead">Отказы — это плюс: система не отдала ПДн и не дала менять данные.</p>
              <div className="dash-ok">
                <div>
                  <strong>{security.pdn.toLocaleString('ru-RU')}</strong>
                  <span>ПДн</span>
                </div>
                <div>
                  <strong>{security.mutation.toLocaleString('ru-RU')}</strong>
                  <span>Изменение</span>
                </div>
              </div>
              {security.other.length > 0 && (
                <ul className="dash-other">
                  {security.other.map((row) => (
                    <li key={row.code}>
                      {row.code} · {row.count}
                    </li>
                  ))}
                </ul>
              )}
            </article>
          </div>

          <article className="dash-card">
            <h2>Последние запросы</h2>
            {recent.length === 0 ? (
              <p className="muted dash-empty">Лента пока пустая.</p>
            ) : (
              <ul className="dash-feed">
                {recent.map((q, i) => (
                  <li key={i}>
                    <div className="dash-feed-meta">
                      <span>{ROLE_LABEL[q.role] || q.role}</span>
                      <span className={q.status === 'success' ? 'ok' : 'bad'}>
                        {q.status === 'success' ? 'успех' : 'отказ'}
                      </span>
                      {q.latency_ms != null && <span>{fmtMs(q.latency_ms)}</span>}
                    </div>
                    <p>{q.question || '—'}</p>
                    {q.sql_preview ? <pre>{q.sql_preview}</pre> : null}
                  </li>
                ))}
              </ul>
            )}
          </article>

          <div className="dash-journal-bar">
            <p className="muted">Сырой журнал — только для разбора и выгрузки.</p>
            <div>
              {!journal && (
                <button type="button" className="ghost analytics-more" onClick={showJournal} disabled={logBusy}>
                  {logBusy ? 'Загрузка…' : 'Открыть журнал'}
                </button>
              )}
              <button type="button" className="ghost analytics-more" onClick={exportCsv} disabled={logBusy}>
                Скачать CSV
              </button>
            </div>
          </div>
          {logError && <p className="muted">{logError}</p>}
          {journal && rows && rows.length === 0 && <p className="muted">Запросов ещё нет.</p>}
          {journal && rows?.length > 0 && (
            <>
              <p className="analytics-meta">
                {open || !extra
                  ? `${rows.length} записей`
                  : `${PREVIEW} из ${rows.length} записей`}
              </p>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      {cols.map(([key, label]) => (
                        <th key={key}>{label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((row, i) => (
                      <tr key={row.query_id || i}>
                        {cols.map(([key]) => (
                          <td key={key}>{formatCell(key, row[key])}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {extra && (
                <button type="button" className="ghost analytics-more" onClick={() => setOpen((v) => !v)}>
                  {open ? 'Свернуть' : `Показать все ${rows.length}`}
                </button>
              )}
            </>
          )}
        </>
      )}
    </section>
  )
}

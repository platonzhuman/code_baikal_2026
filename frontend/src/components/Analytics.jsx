import { useEffect, useState } from 'react'
import { fetchLogs } from '../api'

export default function Analytics() {
  const [rows, setRows] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    fetchLogs()
      .then(setRows)
      .catch(() => setError('Журнал запросов пока недоступен.'))
  }, [])

  return (
    <section className="sheet glass">
      <p className="kicker">Журнал</p>
      <h1>Аналитика запросов</h1>
      {error && <p className="muted">{error}</p>}
      {!error && !rows && <p className="muted">Загрузка…</p>}
      {rows && rows.length === 0 && <p className="muted">Запросов ещё нет.</p>}
      {rows?.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>{Object.keys(rows[0]).map((c) => <th key={c}>{c}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i}>
                  {Object.keys(rows[0]).map((c) => <td key={c}>{String(row[c])}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

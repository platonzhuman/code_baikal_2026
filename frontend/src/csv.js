export function downloadCsv(result, filename = 'result.csv') {
  if (!result?.columns || !result?.rows) return
  const lines = [
    result.columns.join(','),
    ...result.rows.map((row) =>
      result.columns.map((c) => `"${String(row[c] ?? '').replaceAll('"', '""')}"`).join(','),
    ),
  ]
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}

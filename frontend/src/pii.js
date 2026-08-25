const HIDDEN = /fio|email|phone|passport|student_card/i

export function maskResult(result) {
  if (!result?.columns || !result?.rows) return result
  const hidden = result.columns.filter((c) => HIDDEN.test(c))
  if (!hidden.length) return result
  return {
    ...result,
    rows: result.rows.map((row) => {
      const next = { ...row }
      hidden.forEach((c) => {
        next[c] = '***'
      })
      return next
    }),
  }
}

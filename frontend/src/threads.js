const KEY = 'gigachads_threads'

export function loadThreads() {
  try {
    const data = JSON.parse(localStorage.getItem(KEY) || 'null')
    if (!data?.threads) return { threads: [], currentId: null }
    return data
  } catch {
    return { threads: [], currentId: null }
  }
}

export function saveThreads(state) {
  const payload = {
    currentId: state.currentId,
    threads: state.threads.slice(0, 40),
  }
  try {
    localStorage.setItem(KEY, JSON.stringify(payload))
  } catch {
    payload.threads = payload.threads.slice(0, 8)
    try {
      localStorage.setItem(KEY, JSON.stringify(payload))
    } catch {}
  }
}

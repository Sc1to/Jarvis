const BASE = '/writer/api'

export async function fetchModels() {
  const r = await fetch(`${BASE}/models`)
  const data = await r.json()
  return (data.models || []).map((m) => m.name || m)
}

function streamRequest(endpoint, body, onChunk, onDone, onError) {
  fetch(`${BASE}${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
    .then(async (resp) => {
      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6)
          if (raw === '[DONE]') { onDone?.(); return }
          try {
            const data = JSON.parse(raw)
            if (data.text) onChunk(data.text)
            if (data.error) onError?.(data.error)
          } catch {}
        }
      }
      onDone?.()
    })
    .catch((e) => onError?.(e.message))
}

export const streamWrite = (body, onChunk, onDone, onError) =>
  streamRequest('/write', body, onChunk, onDone, onError)

export const streamContinue = (body, onChunk, onDone, onError) =>
  streamRequest('/continue', body, onChunk, onDone, onError)

export const streamEdit = (body, onChunk, onDone, onError) =>
  streamRequest('/edit', body, onChunk, onDone, onError)

export async function fetchSuggestions(document_so_far, model) {
  const r = await fetch(`${BASE}/suggest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ document_so_far, model }),
  })
  const data = await r.json()
  return data.suggestions || []
}

export interface SSEEvent {
  type: string
  content?: string
  message?: string
  [key: string]: unknown
}

export async function* readSSE(resp: Response): AsyncGenerator<SSEEvent> {
  if (!resp.body) return
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try { yield JSON.parse(line.slice(6)) as SSEEvent } catch {}
    }
  }
}

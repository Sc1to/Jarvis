import { useState, useEffect, useRef } from 'react'
import axios from 'axios'

const API = '/chat/api'

export default function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [model, setModel] = useState(() => localStorage.getItem('model') || 'qwen2.5:14b')
  const [models, setModels] = useState([])
  const [streaming, setStreaming] = useState(false)
  const bottomRef = useRef(null)
  const textareaRef = useRef(null)

  useEffect(() => {
    axios.get(`${API}/models`)
      .then(r => setModels(r.data?.data?.models || []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const selectModel = (m) => {
    setModel(m)
    localStorage.setItem('model', m)
  }

  const send = async () => {
    const text = input.trim()
    if (!text || streaming) return

    const history = [...messages]
    setMessages(prev => [
      ...prev,
      { role: 'user', content: text },
      { role: 'assistant', content: '' },
    ])
    setInput('')
    setStreaming(true)

    try {
      const resp = await fetch(`${API}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, model, history }),
      })

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const chunk = JSON.parse(line.slice(6))
            if (chunk.error) {
              setMessages(prev => replaceLastContent(prev, `Error: ${chunk.error}`))
              break
            }
            if (chunk.message?.content) {
              setMessages(prev => appendLastContent(prev, chunk.message.content))
            }
          } catch {
            // ignore malformed chunks
          }
        }
      }
    } catch {
      setMessages(prev => replaceLastContent(prev, 'Connection error — is Ollama running?'))
    }

    setStreaming(false)
  }

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="flex flex-col h-screen bg-zinc-900 text-zinc-100 font-sans">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800 shrink-0">
        <span className="text-sm font-medium tracking-wide">Chat</span>
        <div className="flex items-center gap-3">
          <select
            value={model}
            onChange={e => selectModel(e.target.value)}
            className="text-xs bg-zinc-800 border border-zinc-700 rounded px-2 py-1.5 text-zinc-300 focus:outline-none focus:border-zinc-500"
          >
            {models.length === 0
              ? <option value={model}>{model}</option>
              : models.map(m => <option key={m.name} value={m.name}>{m.name}</option>)
            }
          </select>
          <button
            onClick={() => setMessages([])}
            className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            Clear
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {messages.length === 0 && (
          <p className="text-center text-zinc-600 text-sm mt-16 select-none">
            Start a conversation.
          </p>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`
              max-w-[85%] sm:max-w-[72%] px-4 py-2.5 rounded-2xl text-sm
              leading-relaxed whitespace-pre-wrap break-words
              ${msg.role === 'user'
                ? 'bg-blue-600 text-white rounded-br-md'
                : 'bg-zinc-800 text-zinc-100 rounded-bl-md'
              }
            `}>
              {msg.content
                ? msg.content
                : streaming && i === messages.length - 1
                  ? <span className="animate-pulse opacity-60">▋</span>
                  : null
              }
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-4 py-3 border-t border-zinc-800 shrink-0">
        <div className="flex gap-2 items-end">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            onInput={e => {
              e.target.style.height = 'auto'
              e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px'
            }}
            placeholder="Message… (Enter to send, Shift+Enter for newline)"
            rows={1}
            disabled={streaming}
            className="
              flex-1 bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2.5
              text-sm resize-none focus:outline-none focus:border-zinc-500
              placeholder-zinc-600 disabled:opacity-50 min-h-[42px] max-h-[120px]
            "
          />
          <button
            onClick={send}
            disabled={streaming || !input.trim()}
            className="
              px-4 py-2.5 bg-blue-600 hover:bg-blue-500 rounded-xl text-sm
              font-medium transition-colors shrink-0
              disabled:opacity-40 disabled:cursor-not-allowed
            "
          >
            {streaming ? '…' : 'Send'}
          </button>
        </div>
      </div>
    </div>
  )
}

function appendLastContent(messages, text) {
  const next = [...messages]
  next[next.length - 1] = { ...next[next.length - 1], content: next[next.length - 1].content + text }
  return next
}

function replaceLastContent(messages, text) {
  const next = [...messages]
  next[next.length - 1] = { ...next[next.length - 1], content: text }
  return next
}

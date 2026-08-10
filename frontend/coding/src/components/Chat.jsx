import { useEffect, useRef, useState } from 'react'
import { streamChat } from '../api.js'

function ToolBlock({ event }) {
  const [open, setOpen] = useState(false)
  const label = event.type === 'tool_call'
    ? `▶ ${event.tool}(${JSON.stringify(event.args ?? {}).slice(0, 60)})`
    : `◀ ${event.tool} result`

  return (
    <div className="my-1">
      <button
        onClick={() => setOpen(o => !o)}
        className="text-xs text-gray-500 hover:text-gray-300 font-mono text-left"
      >
        {label}
      </button>
      {open && (
        <pre className="mt-1 text-xs bg-gray-900 text-gray-400 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all">
          {event.type === 'tool_call'
            ? JSON.stringify(event.args, null, 2)
            : (event.result ?? '')}
        </pre>
      )}
    </div>
  )
}

function Message({ msg }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-3`}>
      <div className={`max-w-[85%] ${isUser ? 'bg-blue-700 text-white' : 'bg-gray-800 text-gray-100'} rounded-lg px-4 py-2`}>
        {/* Tool events */}
        {msg.events?.map((ev, i) => <ToolBlock key={i} event={ev} />)}
        {/* Text content */}
        {msg.content && (
          <pre className="whitespace-pre-wrap text-sm font-sans break-words">{msg.content}</pre>
        )}
        {/* Streaming cursor */}
        {msg.streaming && !msg.content && !msg.events?.length && (
          <span className="text-gray-400 text-sm">Thinking…</span>
        )}
      </div>
    </div>
  )
}

export default function Chat({ projectId, onFileRequest }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Build history in Ollama format (only user+assistant text messages)
  function buildHistory() {
    return messages
      .filter(m => m.role === 'user' || (m.role === 'assistant' && m.content))
      .map(m => ({ role: m.role, content: m.content }))
  }

  async function send() {
    const text = input.trim()
    if (!text || sending) return
    setInput('')
    setSending(true)

    const userMsg = { role: 'user', content: text }
    const assistantMsg = { role: 'assistant', content: '', events: [], streaming: true }

    setMessages(prev => [...prev, userMsg, assistantMsg])

    try {
      await streamChat({
        projectId,
        message: text,
        history: buildHistory(),
        onEvent(ev) {
          setMessages(prev => {
            const next = [...prev]
            const last = { ...next[next.length - 1] }
            if (ev.type === 'text') {
              last.content = (last.content ?? '') + ev.text
            } else if (ev.type === 'tool_call' || ev.type === 'tool_result') {
              last.events = [...(last.events ?? []), ev]
            } else if (ev.type === 'done') {
              last.streaming = false
            }
            next[next.length - 1] = last
            return next
          })
        },
      })
    } catch (e) {
      setMessages(prev => {
        const next = [...prev]
        const last = { ...next[next.length - 1], content: `Error: ${e.message}`, streaming: false }
        next[next.length - 1] = last
        return next
      })
    } finally {
      setSending(false)
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <p className="text-gray-500 text-sm">
              {projectId ? 'Ask me to read, edit, or commit code in your project.' : 'Select a project to unlock tool access, or just chat.'}
            </p>
          </div>
        )}
        {messages.map((msg, i) => <Message key={i} msg={msg} />)}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t border-gray-700 p-3">
        <div className="flex gap-2">
          <textarea
            className="flex-1 bg-gray-800 border border-gray-600 rounded px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-none"
            rows={2}
            placeholder="Ask me to make a change… (Enter to send, Shift+Enter for newline)"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={sending}
          />
          <button
            onClick={send}
            disabled={sending || !input.trim()}
            className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white px-4 rounded text-sm self-end py-2"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  )
}

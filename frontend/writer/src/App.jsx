import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchModels, fetchSuggestions, streamContinue, streamEdit, streamWrite } from './api'

const STORAGE_KEY = 'jarvis_writer_document'
const DEFAULT_MODEL = 'qwen2.5:72b-instruct-q4_K_M'

const TONE_PRESETS = [
  { label: 'Formal',   instruction: 'Rewrite in a formal, professional tone' },
  { label: 'Casual',   instruction: 'Rewrite in a casual, conversational tone' },
  { label: 'Academic', instruction: 'Rewrite in an academic, scholarly tone' },
]

function wordCount(text) {
  return text.trim() ? text.trim().split(/\s+/).length : 0
}

function exportAs(text, format) {
  const blob = new Blob([text], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `document.${format === 'markdown' ? 'md' : 'txt'}`
  a.click()
  URL.revokeObjectURL(url)
}

export default function App() {
  const [document, setDocument] = useState(() => localStorage.getItem(STORAGE_KEY) || '')
  const [model, setModel] = useState(DEFAULT_MODEL)
  const [models, setModels] = useState([DEFAULT_MODEL])
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [suggestions, setSuggestions] = useState([])
  const [loadingSuggestions, setLoadingSuggestions] = useState(false)
  const [customPrompt, setCustomPrompt] = useState('')
  const [status, setStatus] = useState('')

  const textareaRef = useRef(null)
  // Store selection at the moment a tool is invoked
  const selectionRef = useRef({ start: 0, end: 0 })

  // Persist document to localStorage
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, document)
  }, [document])

  // Load model list
  useEffect(() => {
    fetchModels()
      .then((list) => { if (list.length) setModels(list) })
      .catch(() => {})
  }, [])

  const captureSelection = () => {
    const ta = textareaRef.current
    if (!ta) return { start: 0, end: ta?.value.length ?? 0 }
    selectionRef.current = { start: ta.selectionStart, end: ta.selectionEnd }
    return selectionRef.current
  }

  // Insert text at cursor / replace selection
  const insertText = useCallback((chunk, replaceSelection = false) => {
    setDocument((prev) => {
      if (!replaceSelection) return prev + chunk
      const { start, end } = selectionRef.current
      // On first chunk of a replace, clear the selection slot so subsequent chunks append
      selectionRef.current = { start, end: start }
      return prev.slice(0, start) + chunk + prev.slice(end)
    })
  }, [])

  const appendText = useCallback((chunk) => {
    setDocument((prev) => prev + chunk)
  }, [])

  // ── Tool handlers ────────────────────────────────────────────────────────

  const handleContinue = () => {
    if (streaming) return
    setStreaming(true)
    setStatus('Continuing…')
    streamContinue(
      { document_so_far: document, model },
      (chunk) => appendText(chunk),
      () => { setStreaming(false); setStatus('') },
      (e) => { setStreaming(false); setStatus(`Error: ${e}`) },
    )
  }

  const handleEdit = (instruction) => {
    if (streaming) return
    const { start, end } = captureSelection()
    const selection = document.slice(start, end)
    if (!selection) { setStatus('Select text first'); return }

    setStreaming(true)
    setStatus('Editing…')

    // We'll accumulate the replacement then splice it in once done
    let replacement = ''
    streamEdit(
      { selection, instruction, full_document: document, model },
      (chunk) => { replacement += chunk },
      () => {
        setDocument((prev) => prev.slice(0, start) + replacement + prev.slice(end))
        setStreaming(false)
        setStatus('')
      },
      (e) => { setStreaming(false); setStatus(`Error: ${e}`) },
    )
  }

  const handleSuggest = async () => {
    setLoadingSuggestions(true)
    setSuggestions([])
    try {
      const list = await fetchSuggestions(document, model)
      setSuggestions(list)
    } catch (e) {
      setStatus(`Error: ${e.message}`)
    } finally {
      setLoadingSuggestions(false)
    }
  }

  const handleCustomPrompt = () => {
    if (!customPrompt.trim() || streaming) return
    const { start, end } = captureSelection()
    const selection = document.slice(start, end)

    if (selection) {
      handleEdit(customPrompt)
    } else {
      setStreaming(true)
      setStatus('Writing…')
      streamWrite(
        { prompt: customPrompt, document_so_far: document, model },
        (chunk) => appendText(chunk),
        () => { setStreaming(false); setStatus('') },
        (e) => { setStreaming(false); setStatus(`Error: ${e}`) },
      )
    }
    setCustomPrompt('')
  }

  const handleSummarise = () => handleEdit('Summarise this text concisely in plain prose')

  // ── Sidebar ──────────────────────────────────────────────────────────────

  const Sidebar = () => (
    <div className="flex flex-col h-full overflow-y-auto p-4 gap-5">
      {/* Model selector */}
      <div>
        <label className="block text-xs text-gray-500 mb-1">Model</label>
        <select
          className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200"
          value={model}
          onChange={(e) => setModel(e.target.value)}
        >
          {models.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>

      {/* Continue */}
      <ToolButton onClick={handleContinue} disabled={streaming} label="Continue writing" />

      {/* Tone presets */}
      <div>
        <p className="text-xs text-gray-500 mb-2">Change tone (select text first)</p>
        <div className="flex flex-col gap-1.5">
          {TONE_PRESETS.map((t) => (
            <ToolButton key={t.label} onClick={() => handleEdit(t.instruction)} disabled={streaming} label={t.label} />
          ))}
        </div>
      </div>

      {/* Improve & Summarise */}
      <div className="flex flex-col gap-1.5">
        <ToolButton onClick={() => handleEdit('Improve this text: fix grammar, clarity, and flow')} disabled={streaming} label="Improve selected" />
        <ToolButton onClick={handleSummarise} disabled={streaming} label="Summarise selected" />
      </div>

      {/* Suggest improvements */}
      <div>
        <ToolButton onClick={handleSuggest} disabled={streaming || loadingSuggestions} label="Suggest improvements" />
        {loadingSuggestions && <p className="text-xs text-gray-500 mt-2">Analysing…</p>}
        {suggestions.length > 0 && (
          <ul className="mt-2 space-y-1.5">
            {suggestions.map((s, i) => (
              <li key={i} className="text-xs text-gray-400 bg-gray-800 rounded p-2 leading-relaxed">{s}</li>
            ))}
          </ul>
        )}
      </div>

      {/* Custom prompt */}
      <div>
        <p className="text-xs text-gray-500 mb-1.5">Custom instruction</p>
        <textarea
          className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 resize-none h-20"
          placeholder="e.g. Add more detail to the third paragraph"
          value={customPrompt}
          onChange={(e) => setCustomPrompt(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleCustomPrompt() }}
        />
        <button
          className="mt-1.5 w-full bg-blue-700 hover:bg-blue-600 disabled:opacity-40 text-white text-xs font-medium py-1.5 rounded"
          onClick={handleCustomPrompt}
          disabled={streaming || !customPrompt.trim()}
        >
          Apply (⌘↵)
        </button>
      </div>

      {/* Export */}
      <div>
        <p className="text-xs text-gray-500 mb-1.5">Export</p>
        <div className="flex gap-2">
          <button
            className="flex-1 bg-gray-700 hover:bg-gray-600 text-gray-200 text-xs py-1.5 rounded"
            onClick={() => exportAs(document, 'txt')}
          >Plain text</button>
          <button
            className="flex-1 bg-gray-700 hover:bg-gray-600 text-gray-200 text-xs py-1.5 rounded"
            onClick={() => exportAs(document, 'markdown')}
          >Markdown</button>
        </div>
      </div>
    </div>
  )

  const wc = wordCount(document)

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100 overflow-hidden">
      {/* Main editor column */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="flex items-center px-4 md:px-8 py-3 border-b border-gray-800 gap-3 flex-shrink-0">
          <span className="text-gray-500 text-sm font-medium tracking-wide">Writer</span>

          <div className="flex items-center gap-2 ml-auto">
            {status && (
              <span className="text-xs text-blue-400 animate-pulse">{status}</span>
            )}
            <span className="text-xs text-gray-600">{wc} {wc === 1 ? 'word' : 'words'}</span>
            {streaming && (
              <button
                className="text-xs text-red-400 hover:text-red-300 border border-red-800 rounded px-2 py-0.5"
                onClick={() => setStreaming(false)}
              >Stop</button>
            )}
            <button
              className="text-xs text-gray-400 hover:text-gray-200 border border-gray-700 rounded px-2 py-0.5"
              onClick={() => { if (window.confirm('Clear document?')) setDocument('') }}
            >Clear</button>
            <button
              className={`text-xs px-2 py-0.5 rounded border ${sidebarOpen ? 'border-blue-600 text-blue-400' : 'border-gray-700 text-gray-400 hover:text-gray-200'}`}
              onClick={() => setSidebarOpen((p) => !p)}
            >Tools</button>
          </div>
        </header>

        {/* Editor */}
        <div className="flex-1 overflow-y-auto px-4 md:px-8 py-6">
          <div className="max-w-2xl mx-auto">
            <textarea
              ref={textareaRef}
              className="editor-area"
              placeholder="Start writing, or use the Tools panel to generate content…"
              value={document}
              onChange={(e) => setDocument(e.target.value)}
              onMouseUp={captureSelection}
              onKeyUp={captureSelection}
              spellCheck
            />
          </div>
        </div>
      </div>

      {/* Sidebar — desktop inline, mobile overlay */}
      {sidebarOpen && (
        <>
          {/* Mobile backdrop */}
          <div
            className="md:hidden fixed inset-0 bg-black/50 z-20"
            onClick={() => setSidebarOpen(false)}
          />
          <aside className="fixed right-0 inset-y-0 z-30 w-64 bg-gray-900 border-l border-gray-800 md:relative md:inset-auto md:z-auto">
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
              <span className="text-xs font-medium text-gray-400">Writing Tools</span>
              <button className="text-gray-600 hover:text-gray-300 text-lg leading-none" onClick={() => setSidebarOpen(false)}>✕</button>
            </div>
            <Sidebar />
          </aside>
        </>
      )}
    </div>
  )
}

function ToolButton({ onClick, disabled, label }) {
  return (
    <button
      className="w-full text-left bg-gray-800 hover:bg-gray-700 disabled:opacity-40 text-gray-200 text-sm px-3 py-2 rounded"
      onClick={onClick}
      disabled={disabled}
    >
      {label}
    </button>
  )
}

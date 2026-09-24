import { useState } from 'react'
import { Copy, Check } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Props {
  text: string
  className?: string
  /** Optional label shown next to the icon. Icon-only when omitted. */
  label?: string
}

/** Small copy-to-clipboard button for streamed/generated text fields. */
export default function CopyButton({ text, className, label }: Props) {
  const [copied, setCopied] = useState(false)

  async function handleCopy(e: React.MouseEvent) {
    e.stopPropagation()
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      // Clipboard API unavailable (e.g. insecure context) — fall back to a hidden textarea
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      try { document.execCommand('copy') } catch { /* give up silently */ }
      document.body.removeChild(ta)
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      disabled={!text}
      title={copied ? 'Copied!' : 'Copy to clipboard'}
      className={cn(
        'inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors disabled:opacity-30 disabled:cursor-not-allowed shrink-0',
        className,
      )}
    >
      {copied ? <Check size={12} className="text-emerald-500" /> : <Copy size={12} />}
      {label && <span>{copied ? 'Copied' : label}</span>}
    </button>
  )
}

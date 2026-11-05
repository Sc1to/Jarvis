import { useState } from 'react'
import { api, bookPath } from '../../lib/api'
import { useAction, useApi, useJob } from '../../lib/hooks'
import type { Rule, RuleHealth, RuleStat, RuleTest, SceneRow } from '../../lib/types'
import { Button, Card, Empty, ErrorBanner, Loading } from '../../components/ui'

const TYPES: [Rule['type'], string, string][] = [
  ['banned_phrase', 'Banned phrase', 'checked mechanically in every scene'],
  ['style_rule', 'Style rule', 'given to the writer; the critic scores against it'],
  ['hard_constraint', 'Hard constraint', 'asked as a yes/no question on every scene'],
  ['character_voice', 'Character voice', 'for one character, given to the writer and the critic'],
]
const SEV_TONE = { block: 'bg-red-100 text-red-800', warn: 'bg-amber-100 text-amber-900', note: 'bg-slate-100 text-slate-700' }
const BLANK: Rule = { id: '', type: 'style_rule', text: '', example: '', scope: 'series', target: '', severity: 'warn', phrase: '', enabled: true }

export default function Rules({ series, book }: { series: string; book: string }) {
  const base = bookPath(series, book)
  const data = useApi<{ rules: Rule[]; stats: RuleStat[]; health: RuleHealth[] }>(`${base}/workbench/rules`)
  const scenes = useApi<SceneRow[]>(`${base}/scenes`)
  const [draft, setDraft] = useState<Rule | null>(null)
  const save = useAction()
  const test = useJob<RuleTest>(base)
  const propose = useJob<Rule>(base)
  const [fb, setFb] = useState({ scene: '', passage: '', comment: '' })
  const stats = new Map(data.data?.stats.map((s) => [s.id, s]))

  const set = (patch: Partial<Rule>) => setDraft((d) => (d ? { ...d, ...patch } : d))
  const submit = async () => {
    if (!draft) return
    const ok = await save.run(() => api(`${base}/workbench/rules/${encodeURIComponent(draft.id)}`, { method: 'PUT', body: draft }))
    if (ok) { setDraft(null); test.reset(); data.reload() }
  }
  const remove = async (id: string) => {
    if (window.confirm(`Delete the rule ${id}?`) && (await save.run(() => api(`${base}/workbench/rules/${encodeURIComponent(id)}`, { method: 'DELETE' })))) data.reload()
  }
  const toggle = async (r: Rule) => { if (await save.run(() => api(`${base}/workbench/rules/${encodeURIComponent(r.id)}`, { method: 'PUT', body: { ...r, enabled: !r.enabled } }))) data.reload() }
  const useProposal = () => { if (propose.result) { setDraft({ ...BLANK, ...propose.result }); propose.reset() } }

  if (data.error) return <ErrorBanner message={data.error} />
  if (!data.data) return <Loading />

  return (
    <div className="space-y-3">
      <ErrorBanner message={save.error} onClose={save.clear} />
      {data.data.health.length > 0 && (
        <Card title="Rule health" tone="warn">
          <ul className="space-y-1 text-sm">{data.data.health.map((h, i) => <li key={i}><span className="font-medium">{h.rule}</span> · {h.problem.replace(/_/g, ' ')}: {h.detail}</li>)}</ul>
        </Card>
      )}

      <Card title={`Rules (${data.data.rules.length})`} right={<Button onClick={() => { setDraft({ ...BLANK }); test.reset() }}>New rule</Button>}>
        {!data.data.rules.length && <Empty>No rules yet. A rule is a do or a don't that the checks enforce.</Empty>}
        <ul className="divide-y divide-slate-100">
          {data.data.rules.map((r) => {
            const s = stats.get(r.id)
            return (
              <li key={r.id} className={`py-3 ${r.enabled ? '' : 'opacity-50'}`}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{r.id}</span>
                  <span className={`rounded-full px-2 py-0.5 text-xs ${SEV_TONE[r.severity]}`}>{r.severity}</span>
                  <span className="text-xs text-slate-500">{r.type.replace(/_/g, ' ')} · {r.scope}{r.target ? `: ${r.target}` : ''}</span>
                </div>
                <p className="mt-1 text-sm">{r.type === 'banned_phrase' ? <code className="rounded bg-slate-100 px-1">{r.phrase}</code> : r.text}</p>
                {s && (s.measured
                  ? <p className="mt-1 text-xs text-slate-600">Fired in {s.fired} of {s.written} written scenes ({s.applicable} apply){s.hits.length > 0 && ': ' + s.hits.map((h) => `${h.scene.split('.').slice(1).join('.')} “${h.what}”`).join('; ')}</p>
                  : <p className="mt-1 text-xs text-slate-500">Judged by the critic: no count.</p>)}
                <div className="mt-2 flex flex-wrap gap-2">
                  <Button onClick={() => { setDraft(r); test.reset() }}>Edit</Button>
                  <Button onClick={() => toggle(r)} disabled={save.busy}>{r.enabled ? 'Turn off' : 'Turn on'}</Button>
                  <Button kind="danger" onClick={() => remove(r.id)} disabled={save.busy}>Delete</Button>
                </div>
              </li>
            )
          })}
        </ul>
      </Card>

      {draft && (
        <Card title={data.data.rules.some((r) => r.id === draft.id) ? `Edit ${draft.id}` : 'New rule'}>
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void submit() }}>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block text-sm">Id
                <input value={draft.id} onChange={(e) => set({ id: e.target.value })} pattern="[a-z][a-z0-9\-]*" required className="mt-1 w-full rounded-md border border-slate-300 p-2" placeholder="no-purple-prose" />
              </label>
              <label className="block text-sm">Type
                <select value={draft.type} onChange={(e) => set({ type: e.target.value as Rule['type'], scope: e.target.value === 'character_voice' ? 'character' : draft.scope })} className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2">
                  {TYPES.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                </select>
                <span className="text-xs text-slate-500">{TYPES.find(([k]) => k === draft.type)?.[2]}</span>
              </label>
              <label className="block text-sm">Severity
                <select value={draft.severity} onChange={(e) => set({ severity: e.target.value as Rule['severity'] })} className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2">
                  <option value="block">block: fails the check, gets revised</option><option value="warn">warn: in the morning report</option><option value="note">note: only recorded</option>
                </select>
              </label>
              <label className="block text-sm">Scope
                <select value={draft.scope} onChange={(e) => set({ scope: e.target.value as Rule['scope'] })} disabled={draft.type === 'character_voice'} className="mt-1 w-full rounded-md border border-slate-300 bg-white p-2">
                  <option value="series">series</option><option value="book">book</option><option value="character">character</option><option value="scene">scene</option>
                </select>
              </label>
              {(draft.scope === 'character' || draft.scope === 'scene' || draft.scope === 'book') && (
                <label className="block text-sm sm:col-span-2">Target <span className="text-slate-500">({draft.scope === 'character' ? 'character id, like anna' : draft.scope === 'scene' ? 'scene id, like b1.ch02.s1' : 'book id'})</span>
                  <input value={draft.target} onChange={(e) => set({ target: e.target.value })} className="mt-1 w-full rounded-md border border-slate-300 p-2" />
                </label>
              )}
            </div>
            {draft.type === 'banned_phrase' && (
              <label className="block text-sm">Phrase <span className="text-slate-500">(start with re: for a regular expression)</span>
                <input value={draft.phrase} onChange={(e) => set({ phrase: e.target.value })} required className="mt-1 w-full rounded-md border border-slate-300 p-2" />
              </label>
            )}
            <label className="block text-sm">The rule in plain words
              <textarea value={draft.text} onChange={(e) => set({ text: e.target.value })} required rows={2} className="mt-1 w-full rounded-md border border-slate-300 p-2" />
            </label>
            <label className="block text-sm">Example <span className="text-slate-500">(what to avoid, or do instead)</span>
              <textarea value={draft.example} onChange={(e) => set({ example: e.target.value })} rows={2} className="mt-1 w-full rounded-md border border-slate-300 p-2" />
            </label>
            <div className="flex flex-wrap gap-2">
              <Button type="submit" kind="primary" disabled={save.busy}>Save</Button>
              <Button disabled={test.busy || !draft.text} onClick={() => test.run('/workbench/rules-test', { rule: draft })} title="Try the rule on chapter 1 before saving">{test.busy ? 'Testing…' : 'Test on chapter 1'}</Button>
              <Button onClick={() => { setDraft(null); test.reset() }}>Cancel</Button>
            </div>
            <ErrorBanner message={test.error} />
            {test.result && (
              <div className="rounded-md border border-slate-200 p-2 text-sm">
                <p className="font-medium">{test.result.total_hits ? `It would catch ${test.result.total_hits} thing(s):` : 'It would catch nothing in chapter 1.'}</p>
                <ul className="mt-1 space-y-1">{test.result.scenes.map((s) => (
                  <li key={s.scene} className="text-xs">
                    <span className="font-medium">{s.scene}</span>{!s.applies && ' (the rule does not apply here)'}{s.error && <span className="text-red-700"> {s.error}</span>}
                    {s.hits.map((h, i) => <div key={i} className="ml-3 italic text-slate-700">“{h}”</div>)}
                  </li>
                ))}</ul>
              </div>
            )}
          </form>
        </Card>
      )}

      <Card title="Turn a comment into a rule">
        <p className="mb-2 text-sm text-slate-600">Paste a passage that bothers you and say why. A rule is proposed; you edit and save it.</p>
        <div className="space-y-2">
          <select value={fb.scene} onChange={(e) => setFb({ ...fb, scene: e.target.value })} aria-label="Scene" className="min-h-10 w-full rounded-md border border-slate-300 bg-white px-2 text-sm">
            <option value="">choose the scene</option>{scenes.data?.map((s) => <option key={s.id} value={s.id}>{s.id}</option>)}
          </select>
          <textarea value={fb.passage} onChange={(e) => setFb({ ...fb, passage: e.target.value })} rows={3} placeholder="The passage" className="w-full rounded-md border border-slate-300 p-2 text-sm" />
          <input value={fb.comment} onChange={(e) => setFb({ ...fb, comment: e.target.value })} placeholder="Your comment: too purple, she would never say that…" className="min-h-10 w-full rounded-md border border-slate-300 px-2 text-sm" />
          <Button disabled={propose.busy || !fb.scene || !fb.passage.trim() || !fb.comment.trim()} onClick={() => propose.run('/workbench/rules-propose', fb)}>{propose.busy ? 'Thinking…' : 'Propose a rule'}</Button>
          <ErrorBanner message={propose.error} />
          {propose.result && (
            <div className="rounded-md border border-emerald-200 bg-emerald-50 p-2 text-sm">
              <p><span className="font-medium">{propose.result.id}</span> · {propose.result.type.replace(/_/g, ' ')} · {propose.result.severity} · {propose.result.scope}{propose.result.target ? `: ${propose.result.target}` : ''}</p>
              <p className="mt-1">{propose.result.text}</p>
              <div className="mt-2"><Button kind="primary" onClick={useProposal}>Edit and save it</Button></div>
            </div>
          )}
        </div>
      </Card>
    </div>
  )
}

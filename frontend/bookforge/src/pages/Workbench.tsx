import { useState } from 'react'
import Arc from './workbench/Arc'
import Briefing from './workbench/Briefing'
import Calibration from './workbench/Calibration'
import Experiments from './workbench/Experiments'
import Prompts from './workbench/Prompts'
import Rules from './workbench/Rules'

const VIEWS: [string, string][] = [['rules', 'Rules'], ['briefing', 'Briefing'], ['prompts', 'Prompts'], ['experiments', 'Experiments'], ['calibration', 'Calibration'], ['arc', 'Arc']]

/** The second dashboard mode: tuning bookforge itself. Everything here edits files in the series' workbench/ folder. */
export default function Workbench({ series, book }: { series: string; book: string }) {
  const [view, setView] = useState('rules')
  const [experiment, setExperiment] = useState('')
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600">Tune how the book is written: rules, prompts, and what the model is given. Changes are files in <code className="rounded bg-slate-100 px-1">workbench/</code>, kept in Git.</p>
      <div role="tablist" aria-label="Workbench" className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1">
        {VIEWS.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={view === k} onClick={() => setView(k)}
            className={`min-h-10 shrink-0 rounded-md px-3 text-sm ${view === k ? 'bg-slate-700 text-white' : 'border border-slate-300 bg-white'}`}>{label}</button>
        ))}
      </div>
      {view === 'rules' && <Rules series={series} book={book} />}
      {view === 'briefing' && <Briefing series={series} book={book} />}
      {view === 'prompts' && <Prompts series={series} book={book} onExperiment={(n) => { setExperiment(n); setView('experiments') }} />}
      {view === 'experiments' && <Experiments series={series} book={book} selected={experiment} onSelect={setExperiment} />}
      {view === 'calibration' && <Calibration series={series} book={book} />}
      {view === 'arc' && <Arc series={series} book={book} />}
    </div>
  )
}

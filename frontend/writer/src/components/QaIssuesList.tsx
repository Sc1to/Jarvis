import { cn } from '@/lib/utils'

export interface QaIssue {
  type: string
  description: string
  severity: string
}

export default function QaIssuesList({ issues }: { issues: QaIssue[] }) {
  if (issues.length === 0) return null
  return (
    <ul className="space-y-0.5">
      {issues.map((iss, i) => (
        <li key={i} className="text-xs">
          <span className={cn('font-mono text-[10px] uppercase mr-1', iss.severity === 'error' ? 'text-red-500' : 'text-muted-foreground')}>
            {iss.severity}
          </span>
          {iss.description}
        </li>
      ))}
    </ul>
  )
}

import { useState } from 'react'

function TreeNode({ node, onFileClick }) {
  const [open, setOpen] = useState(node.type === 'directory' && node.name !== 'node_modules')

  if (node.type === 'file') {
    return (
      <button
        onClick={() => onFileClick(node.path)}
        className="flex items-center gap-1 w-full text-left px-2 py-0.5 text-xs text-gray-300 hover:text-white hover:bg-gray-700 rounded truncate"
      >
        <span className="text-gray-500">›</span>
        {node.name}
      </button>
    )
  }

  return (
    <div>
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1 w-full text-left px-2 py-0.5 text-xs text-gray-400 hover:text-white font-medium"
      >
        <span>{open ? '▾' : '▸'}</span>
        {node.name}
      </button>
      {open && node.children?.length > 0 && (
        <div className="pl-3 border-l border-gray-700 ml-2">
          {node.children.map((child, i) => (
            <TreeNode key={i} node={child} onFileClick={onFileClick} />
          ))}
        </div>
      )}
    </div>
  )
}

export default function FileTree({ tree, onFileClick, loading }) {
  if (loading) return <p className="text-xs text-gray-500 px-2">Loading…</p>
  if (!tree) return <p className="text-xs text-gray-500 px-2">No project selected</p>

  return (
    <div className="overflow-y-auto flex-1 py-1">
      {tree.children?.map((node, i) => (
        <TreeNode key={i} node={node} onFileClick={onFileClick} />
      ))}
    </div>
  )
}

import { Navigate, Route, Routes } from 'react-router-dom'
import { BookLayout, GlobalLayout } from './components/Layout'
import BooksPage from './pages/Books'
import SettingsPage from './pages/Settings'
import NorthStarPage from './pages/NorthStar'
import BibleWorkshopPage from './pages/BibleWorkshop'
import BibleViewerPage from './pages/BibleViewer'
import WritingLoopPage from './pages/WritingLoop'
import HistoryPage from './pages/History'
import SequentialWorkflowPage from './pages/SequentialWorkflow'

export default function App() {
  return (
    <Routes>
      {/* Root → books list */}
      <Route index element={<Navigate to="/books" replace />} />

      {/* Books list — no layout chrome needed */}
      <Route path="/books" element={<BooksPage />} />

      {/* Global pages */}
      <Route element={<GlobalLayout />}>
        <Route path="/settings" element={<SettingsPage />} />
      </Route>

      {/* Per-book pages */}
      <Route path="/books/:bookId" element={<BookLayout />}>
        <Route index element={<Navigate to="north-star" replace />} />
        <Route path="north-star" element={<NorthStarPage />} />
        <Route path="bible-workshop" element={<BibleWorkshopPage />} />
        <Route path="bible-viewer" element={<BibleViewerPage />} />
        <Route path="work" element={<SequentialWorkflowPage />} />
        <Route path="writing-loop" element={<WritingLoopPage />} />
        <Route path="history" element={<HistoryPage />} />
      </Route>
    </Routes>
  )
}

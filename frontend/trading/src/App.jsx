import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout.jsx'
import Dashboard from './views/Dashboard.jsx'
import Positions from './views/Positions.jsx'
import Signals from './views/Signals.jsx'
import WSB from './views/WSB.jsx'
import Catalysts from './views/Catalysts.jsx'
import AuditLog from './views/AuditLog.jsx'
import Settings from './views/Settings.jsx'
import Validation from './views/Validation.jsx'

export default function App() {
  return (
    <BrowserRouter basename="/trading">
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="positions" element={<Positions />} />
          <Route path="signals" element={<Signals />} />
          <Route path="wsb" element={<WSB />} />
          <Route path="catalysts" element={<Catalysts />} />
          <Route path="audit" element={<AuditLog />} />
          <Route path="settings" element={<Settings />} />
          <Route path="validation" element={<Validation />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

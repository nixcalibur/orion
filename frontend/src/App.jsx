import { BrowserRouter, Routes, Route, Outlet } from 'react-router-dom'
import Sidebar from './components/Sidebar.jsx'
import Dashboard from './pages/Dashboard.jsx'
import SubmissionList from './pages/SubmissionList.jsx'
import SubmissionDetail from './pages/SubmissionDetail.jsx'
import NewSubmission from './pages/NewSubmission.jsx'

function Layout() {
  return (
    <div className="flex h-screen overflow-hidden" style={{ background: '#0f1117' }}>
      <Sidebar />
      <main className="flex-1 overflow-y-auto p-6">
        <Outlet />
      </main>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/submissions" element={<SubmissionList />} />
          <Route path="/submissions/:id" element={<SubmissionDetail />} />
          <Route path="/submit" element={<NewSubmission />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

import { useState } from 'react'
import Sidebar from './components/Sidebar.jsx'
import StudentChat from './pages/StudentChat.jsx'
import TeacherPanel from './pages/TeacherPanel.jsx'

export default function App() {
  const [activePage, setActivePage] = useState('student')

  return (
    <div className="flex h-screen overflow-hidden bg-base">
      <Sidebar activePage={activePage} onNavigate={setActivePage} />
      <div className="flex-1 overflow-hidden">
        {activePage === 'student' ? <StudentChat /> : <TeacherPanel />}
      </div>
    </div>
  )
}

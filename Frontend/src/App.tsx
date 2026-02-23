import { BrowserRouter, Route, Routes } from 'react-router-dom'

import Layout from './components/Layout'
import HomePage from './pages/HomePage'
import CoursesPage from './pages/CoursesPage'
import CourseDetailPage from './pages/CourseDetailPage'
import ProfessorDashboardPage from './pages/professor/ProfessorDashboardPage'
import StudentDashboardPage from './pages/student/StudentDashboardPage'
import TopicsPage from './pages/professor/TopicsPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/courses" element={<CoursesPage />} />
          <Route path="/courses/:courseId" element={<CourseDetailPage />} />
          <Route path="/courses/:courseId/topics" element={<TopicsPage />} />
          <Route path="/professor" element={<ProfessorDashboardPage />} />
          <Route path="/student" element={<StudentDashboardPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

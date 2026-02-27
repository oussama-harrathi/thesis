import { BrowserRouter, Route, Routes } from 'react-router-dom'

import Layout from './components/Layout'
import HomePage from './pages/HomePage'
import CoursesPage from './pages/CoursesPage'
import CourseDetailPage from './pages/CourseDetailPage'
import ProfessorDashboardPage from './pages/professor/ProfessorDashboardPage'
import StudentDashboardPage from './pages/student/StudentDashboardPage'
import TopicsPage from './pages/professor/TopicsPage'
import QuestionReviewPage from './pages/professor/QuestionReviewPage'
import ExamBuilderPage from './pages/professor/ExamBuilderPage'
import BlueprintCreatePage from './pages/professor/BlueprintCreatePage'
import GenerationPage from './pages/professor/GenerationPage'
import PracticeCreatePage from './pages/student/PracticeCreatePage'
import PracticeSessionPage from './pages/student/PracticeSessionPage'
import ExportPage from './pages/professor/ExportPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/courses" element={<CoursesPage />} />
          <Route path="/courses/:courseId" element={<CourseDetailPage />} />
          <Route path="/courses/:courseId/topics" element={<TopicsPage />} />
          <Route path="/courses/:courseId/blueprints/new" element={<BlueprintCreatePage />} />
          <Route path="/courses/:courseId/generation/:jobId" element={<GenerationPage />} />
          <Route path="/courses/:courseId/questions" element={<QuestionReviewPage />} />
          <Route path="/courses/:courseId/exam-builder" element={<ExamBuilderPage />} />
          <Route path="/professor" element={<ProfessorDashboardPage />} />
          <Route path="/student" element={<StudentDashboardPage />} />
          <Route path="/student/practice/new" element={<PracticeCreatePage />} />
          <Route path="/student/practice/:questionSetId" element={<PracticeSessionPage />} />
          <Route path="/exams/:examId/export" element={<ExportPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

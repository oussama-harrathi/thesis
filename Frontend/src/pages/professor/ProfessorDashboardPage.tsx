/**
 * ProfessorDashboardPage  — /professor
 *
 * Overview of the professor workflow with links to each step.
 * Displays the list of courses so the professor can jump directly
 * into any step for any course.
 */

import React from 'react'
import { Link } from 'react-router-dom'
import { useCourses } from '../../hooks/useCourses'

export default function ProfessorDashboardPage() {
  const { data: courses, isLoading, error } = useCourses()

  return (
    <div style={s.container}>
      <h1 style={s.heading}>Professor Dashboard</h1>
      <p style={s.subtitle}>
        Manage courses, generate exam questions from your materials, review and assemble exams.
      </p>

      {/* Workflow steps explanation */}
      <div style={s.workflowCard}>
        <h2 style={s.sectionTitle}>Professor Workflow</h2>
        <ol style={s.stepList}>
          <li><strong>Create a course</strong> — <Link to="/courses" style={s.link}>My Courses</Link></li>
          <li><strong>Upload PDFs</strong> — go into a course and upload your materials (auto-processed in background)</li>
          <li><strong>Review topics</strong> — auto-extracted from your PDF; add/edit/delete as needed</li>
          <li><strong>Create a blueprint &amp; generate</strong> — define question counts, difficulty mix, then generate with AI</li>
          <li><strong>Review questions</strong> — approve or reject each generated question</li>
          <li><strong>Assemble exam</strong> — pick approved questions, reorder, set points</li>
          <li><strong>Export</strong> — download exam PDF + answer key (or LaTeX source)</li>
        </ol>
      </div>

      {/* Per-course quick access */}
      <h2 style={s.sectionTitle}>Your Courses</h2>

      {isLoading && <p style={s.muted}>Loading courses…</p>}
      {error && <p style={s.error}>Failed to load courses: {(error as Error).message}</p>}

      {!isLoading && courses?.length === 0 && (
        <p style={s.muted}>
          No courses yet.{' '}
          <Link to="/courses" style={s.link}>Create your first course →</Link>
        </p>
      )}

      {courses && courses.length > 0 && (
        <div style={s.courseGrid}>
          {courses.map(course => (
            <div key={course.id} style={s.courseCard}>
              <h3 style={s.courseName}>{course.name}</h3>
              {course.description && (
                <p style={s.courseDesc}>{course.description}</p>
              )}
              <div style={s.linkRow}>
                <Link to={`/courses/${course.id}`} style={s.chipLink}>📎 Documents</Link>
                <Link to={`/courses/${course.id}/topics`} style={s.chipLink}>🏷️ Topics</Link>
                <Link to={`/courses/${course.id}/blueprints/new`} style={{ ...s.chipLink, ...s.chipPrimary }}>
                  📐 Generate
                </Link>
                <Link to={`/courses/${course.id}/questions`} style={s.chipLink}>📋 Review</Link>
                <Link to={`/courses/${course.id}/exam-builder`} style={s.chipLink}>📝 Exam Builder</Link>
              </div>
            </div>
          ))}
        </div>
      )}

      <p style={{ marginTop: 32 }}>
        <Link to="/courses" style={s.link}>Manage all courses →</Link>
        {' · '}
        <Link to="/" style={s.link}>Home</Link>
      </p>
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  container: { maxWidth: 900, margin: '40px auto', padding: '0 16px', fontFamily: 'system-ui, sans-serif' },
  heading: { margin: '0 0 6px' },
  subtitle: { color: '#555', marginBottom: 28 },
  workflowCard: {
    background: '#f8f8ff', border: '1px solid #dde', borderRadius: 10,
    padding: '20px 24px', marginBottom: 32,
  },
  sectionTitle: { fontSize: '1.05rem', fontWeight: 700, margin: '0 0 12px', borderBottom: '1px solid #eee', paddingBottom: 6 },
  stepList: { margin: 0, paddingLeft: 20, lineHeight: 2 },
  courseGrid: { display: 'flex', flexDirection: 'column', gap: 12 },
  courseCard: {
    background: '#fff', border: '1px solid #e2e4f0', borderRadius: 10,
    padding: '16px 20px', boxShadow: '0 1px 4px rgba(0,0,0,0.04)',
  },
  courseName: { margin: '0 0 4px', fontSize: '1rem', fontWeight: 700 },
  courseDesc: { margin: '0 0 12px', fontSize: '0.85rem', color: '#666' },
  linkRow: { display: 'flex', gap: 8, flexWrap: 'wrap' },
  chipLink: {
    display: 'inline-block', padding: '4px 12px',
    background: '#f0f0f7', color: '#5c6ac4',
    borderRadius: 20, textDecoration: 'none',
    fontSize: '0.82rem', fontWeight: 600,
    border: '1px solid #dde',
  },
  chipPrimary: { background: '#5c6ac4', color: '#fff', border: 'none' },
  muted: { color: '#999', fontSize: '0.9rem' },
  error: { color: '#dc2626' },
  link: { color: '#5c6ac4', textDecoration: 'none', fontWeight: 600 },
}


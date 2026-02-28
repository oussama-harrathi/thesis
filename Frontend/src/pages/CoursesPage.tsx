import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useCourses, useCreateCourse, useDeleteCourse } from '../hooks/useCourses'

export default function CoursesPage() {
  const { data: courses, isLoading, error } = useCourses()
  const createCourse = useCreateCourse()
  const deleteCourse = useDeleteCourse()

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setFormError(null)
    try {
      await createCourse.mutateAsync({ name: name.trim(), description: description.trim() || undefined })
      setName('')
      setDescription('')
      setFormOpen(false)
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : 'Failed to create course.')
    }
  }

  return (
    <div style={s.container}>
      <div style={s.header}>
        <h1 style={s.title}>Courses</h1>
        <button style={s.btnPrimary} onClick={() => setFormOpen(v => !v)}>
          {formOpen ? 'Cancel' : '+ New Course'}
        </button>
      </div>

      {/* Create form */}
      {formOpen && (
        <form onSubmit={handleSubmit} style={s.form}>
          <h2 style={s.formTitle}>Create Course</h2>
          {formError && <p style={s.error}>{formError}</p>}
          <label style={s.label}>
            Name *
            <input
              style={s.input}
              value={name}
              onChange={e => setName(e.target.value)}
              required
              placeholder="e.g. Algorithms 101"
              maxLength={255}
            />
          </label>
          <label style={s.label}>
            Description
            <textarea
              style={{ ...s.input, height: 80, resize: 'vertical' }}
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Optional course description"
              maxLength={4096}
            />
          </label>
          <button style={s.btnPrimary} type="submit" disabled={createCourse.isPending}>
            {createCourse.isPending ? 'Creating…' : 'Create'}
          </button>
        </form>
      )}

      {/* List */}
      {isLoading && <p style={s.muted}>Loading courses…</p>}
      {error && <p style={s.error}>Failed to load courses: {error.message}</p>}
      {!isLoading && courses?.length === 0 && (
        <p style={s.muted}>No courses yet. Click "+ New Course" to get started.</p>
      )}

      <ul style={s.list}>
        {courses?.map(course => (
          <li key={course.id} style={s.card}>
            <div style={s.cardBody}>
              <Link to={`/courses/${course.id}`} style={s.cardTitle}>
                {course.name}
              </Link>
              {course.description && (
                <p style={s.cardDesc}>{course.description}</p>
              )}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <Link to={`/courses/${course.id}`} style={s.cardArrow}>→</Link>
              <button
                style={s.deleteBtn}
                disabled={deleteCourse.isPending}
                onClick={() => {
                  if (window.confirm(`Delete "${course.name}"?\n\nThis will permanently remove the course and all its documents, topics, questions and exams.`))
                    deleteCourse.mutate(course.id)
                }}
              >
                Delete
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  container: { maxWidth: 800, margin: '40px auto', padding: '0 16px', fontFamily: 'system-ui, sans-serif' },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 },
  title: { margin: 0 },
  btnPrimary: {
    padding: '8px 18px', borderRadius: 8, border: 'none',
    background: '#5c6ac4', color: '#fff', cursor: 'pointer', fontWeight: 600,
  },
  form: {
    background: '#f8f9ff', border: '1px solid #dde', borderRadius: 10,
    padding: 20, marginBottom: 28, display: 'flex', flexDirection: 'column', gap: 12,
  },
  formTitle: { margin: 0 },
  label: { display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.9rem', fontWeight: 600 },
  input: { padding: '8px 10px', borderRadius: 6, border: '1px solid #ccc', fontSize: '0.95rem', marginTop: 2 },
  list: { listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 10 },
  card: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    background: '#fff', border: '1px solid #e2e4f0', borderRadius: 10, padding: '14px 18px',
    boxShadow: '0 1px 4px rgba(0,0,0,0.04)',
  },
  cardBody: { display: 'flex', flexDirection: 'column', gap: 4 },
  cardTitle: { fontWeight: 600, fontSize: '1rem', color: '#5c6ac4', textDecoration: 'none' },
  cardDesc: { margin: 0, fontSize: '0.85rem', color: '#666' },
  cardArrow: { fontSize: '1.2rem', color: '#aaa', textDecoration: 'none' },
  deleteBtn: {
    padding: '4px 12px',
    background: 'transparent',
    color: '#c0392b',
    border: '1px solid #e8c4be',
    borderRadius: 6,
    cursor: 'pointer',
    fontWeight: 600,
    fontSize: '0.82rem',
  },
  muted: { color: '#888' },
  error: { color: '#c0392b', background: '#fdf0ee', padding: '8px 12px', borderRadius: 6, margin: 0 },
}

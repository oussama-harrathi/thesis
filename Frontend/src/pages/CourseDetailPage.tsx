import { useParams, Link } from 'react-router-dom'
import { useCourse } from '../hooks/useCourses'
import { useCourseDocuments, useDeleteDocument } from '../hooks/useDocuments'
import UploadDocumentForm from '../components/UploadDocumentForm'

const STATUS_COLOR: Record<string, string> = {
  pending: '#f0a500',
  processing: '#5c6ac4',
  completed: '#27ae60',
  failed: '#c0392b',
}

function formatBytes(bytes: number | null): string {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function CourseDetailPage() {
  const { courseId } = useParams<{ courseId: string }>()

  const { data: course, isLoading: courseLoading, error: courseError } = useCourse(courseId)
  const { data: documents, isLoading: docsLoading, error: docsError } = useCourseDocuments(courseId)
  const deleteMutation = useDeleteDocument(courseId ?? '')

  if (courseLoading) return <div style={s.container}><p style={s.muted}>Loading course…</p></div>
  if (courseError) return (
    <div style={s.container}>
      <p style={s.error}>{courseError.message}</p>
      <Link to="/courses">← Courses</Link>
    </div>
  )
  if (!course) return null

  return (
    <div style={s.container}>
      <p><Link to="/courses" style={s.backLink}>← Courses</Link></p>

      {/* Course info */}
      <div style={s.courseCard}>
        <h1 style={s.title}>{course.name}</h1>
        {course.description && <p style={s.desc}>{course.description}</p>}
        <p style={s.meta}>
          Created {new Date(course.created_at).toLocaleDateString()} &nbsp;·&nbsp;
          ID: <code style={s.code}>{course.id}</code>
        </p>
        <div style={{ marginTop: 12, display: 'flex', gap: 20, flexWrap: 'wrap' }}>
          <Link to={`/courses/${course.id}/topics`} style={s.topicsLink}>
            🏷️ Manage Topics →
          </Link>
          <Link to={`/courses/${course.id}/blueprints/new`} style={s.topicsLink}>
            📐 Create Blueprint & Generate →
          </Link>
          <Link to={`/courses/${course.id}/questions`} style={s.topicsLink}>
            📋 Review Questions →
          </Link>
          <Link to={`/courses/${course.id}/exam-builder`} style={s.topicsLink}>
            📝 Exam Builder →
          </Link>
        </div>
      </div>

      {/* Upload */}
      <section style={s.section}>
        <h2 style={s.sectionTitle}>Upload PDF</h2>
        <UploadDocumentForm courseId={course.id} />
      </section>

      {/* Documents list */}
      <section style={s.section}>
        <h2 style={s.sectionTitle}>Documents</h2>

        {docsLoading && <p style={s.muted}>Loading documents…</p>}
        {docsError && <p style={s.error}>Failed to load documents: {docsError.message}</p>}
        {!docsLoading && documents?.length === 0 && (
          <p style={s.muted}>No documents uploaded yet.</p>
        )}

        {documents && documents.length > 0 && (
          <table style={s.table}>
            <thead>
              <tr>
                {['File', 'Size', 'Status', 'Uploaded', ''].map(h => (
                  <th key={h} style={s.th}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {documents.map(doc => (
                <tr key={doc.id} style={s.tr}>
                  <td style={s.td}>
                    <span title={doc.filename}>{doc.original_filename}</span>
                  </td>
                  <td style={s.td}>{formatBytes(doc.file_size)}</td>
                  <td style={s.td}>
                    <span style={{ ...s.badge, color: STATUS_COLOR[doc.status] ?? '#555' }}>
                      {doc.status}
                    </span>
                  </td>
                  <td style={s.td}>{new Date(doc.created_at).toLocaleString()}</td>
                  <td style={{ ...s.td, textAlign: 'right' }}>
                    <button
                      style={s.deleteBtn}
                      disabled={deleteMutation.isPending}
                      onClick={() => {
                        if (window.confirm(`Delete "${doc.original_filename}"?`))
                          deleteMutation.mutate(doc.id)
                      }}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  container: { maxWidth: 860, margin: '40px auto', padding: '0 16px', fontFamily: 'system-ui, sans-serif' },
  backLink: { color: '#5c6ac4', textDecoration: 'none' },
  topicsLink: {
    color: '#5c6ac4',
    textDecoration: 'none',
    fontWeight: 600,
    fontSize: '0.9rem',
  },
  courseCard: {
    background: '#fff', border: '1px solid #e2e4f0', borderRadius: 12,
    padding: '20px 24px', marginBottom: 28, boxShadow: '0 1px 4px rgba(0,0,0,0.04)',
  },
  title: { margin: '0 0 8px' },
  desc: { margin: '0 0 8px', color: '#444' },
  meta: { margin: 0, fontSize: '0.8rem', color: '#999' },
  code: { background: '#f0f0f0', padding: '1px 5px', borderRadius: 4 },
  section: { marginBottom: 36 },
  sectionTitle: { fontSize: '1.1rem', margin: '0 0 12px', fontWeight: 600, borderBottom: '1px solid #e8e8e8', paddingBottom: 6 },
  table: { width: '100%', borderCollapse: 'collapse', fontSize: '0.88rem' },
  th: { textAlign: 'left', padding: '8px 12px', background: '#f5f5f5', fontWeight: 600, borderBottom: '1px solid #ddd' },
  tr: { borderBottom: '1px solid #f0f0f0' },
  td: { padding: '8px 12px', verticalAlign: 'middle' },
  badge: { fontWeight: 600, textTransform: 'uppercase', fontSize: '0.75rem', letterSpacing: 0.5 },
  deleteBtn: {
    padding: '4px 10px',
    background: 'transparent',
    color: '#c0392b',
    border: '1px solid #e8c4be',
    borderRadius: 5,
    cursor: 'pointer',
    fontSize: '0.8rem',
    fontWeight: 600,
  },
  muted: { color: '#888', margin: 0 },
  error: { color: '#c0392b', background: '#fdf0ee', padding: '8px 12px', borderRadius: 6, margin: 0 },
}

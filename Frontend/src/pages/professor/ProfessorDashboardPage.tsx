import { Link } from 'react-router-dom'

export default function ProfessorDashboardPage() {
  return (
    <div style={styles.container}>
      <h1>Professor Dashboard</h1>
      <p style={styles.subtitle}>
        Manage your courses, generate exam questions, and export exams.
      </p>

      <ul style={styles.list}>
        <li>
          <Link to="/courses">📚 My Courses</Link>
        </li>
        <li style={styles.disabled}>📎 Upload Documents (Phase 3)</li>
        <li style={styles.disabled}>🏷️ Manage Topics (Phase 5)</li>
        <li style={styles.disabled}>📝 Generate Questions (Phase 7)</li>
        <li style={styles.disabled}>📋 Exam Builder (Phase 9)</li>
        <li style={styles.disabled}>📤 Export Exam (Phase 11)</li>
      </ul>

      <p>
        <Link to="/">← Home</Link>
      </p>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    maxWidth: 700,
    margin: '40px auto',
    padding: '0 16px',
    fontFamily: 'system-ui, sans-serif',
  },
  subtitle: {
    color: '#555',
    marginBottom: 32,
  },
  list: {
    lineHeight: 2.2,
    paddingLeft: 24,
    marginBottom: 32,
    fontSize: '1.05rem',
  },
  disabled: {
    color: '#bbb',
  },
}

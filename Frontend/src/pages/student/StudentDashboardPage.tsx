import { Link } from 'react-router-dom'

export default function StudentDashboardPage() {
  return (
    <div style={styles.container}>
      <h1>Student Dashboard</h1>
      <p style={styles.subtitle}>
        Practice with AI-generated questions from your course materials.
      </p>

      <ul style={styles.list}>
        <li>
          <Link to="/student/practice/new">🎯 Start a Practice Session</Link>
        </li>
        <li>
          <Link to="/courses">📚 Browse Courses</Link>
        </li>
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

import { Link } from 'react-router-dom'

export default function HomePage() {
  return (
    <div style={styles.container}>
      <h1 style={styles.title}>AI-Assisted Exam Builder</h1>
      <p style={styles.subtitle}>
        Generate, review, and export exams from your course materials.
      </p>

      <div style={styles.cards}>
        <Link to="/professor" style={styles.card}>
          <h2>👨‍🏫 Professor Mode</h2>
          <p>Generate exam blueprints, review questions, assemble and export exams.</p>
        </Link>

        <Link to="/student" style={styles.card}>
          <h2>🎓 Student Mode</h2>
          <p>Practice with AI-generated questions from your course materials.</p>
        </Link>
      </div>

      <p style={styles.hint}>
        <Link to="/courses">View all courses →</Link>
      </p>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    maxWidth: 720,
    margin: '80px auto',
    textAlign: 'center',
    fontFamily: 'system-ui, sans-serif',
    padding: '0 16px',
  },
  title: {
    fontSize: '2.2rem',
    marginBottom: 12,
    color: '#1a1a2e',
  },
  subtitle: {
    fontSize: '1.1rem',
    color: '#555',
    marginBottom: 48,
  },
  cards: {
    display: 'flex',
    gap: 24,
    justifyContent: 'center',
    flexWrap: 'wrap',
    marginBottom: 40,
  },
  card: {
    display: 'block',
    padding: '32px 28px',
    borderRadius: 12,
    border: '2px solid #e0e0e0',
    textDecoration: 'none',
    color: '#1a1a2e',
    width: 260,
    transition: 'border-color 0.2s, box-shadow 0.2s',
    background: '#fff',
  },
  hint: {
    color: '#888',
    fontSize: '0.95rem',
  },
}

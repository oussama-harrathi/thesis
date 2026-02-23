import { NavLink, Outlet } from 'react-router-dom'

export default function Layout() {
  return (
    <div style={styles.root}>
      <nav style={styles.nav}>
        <NavLink to="/" end style={navStyle}>
          Home
        </NavLink>
        <NavLink to="/courses" style={navStyle}>
          Courses
        </NavLink>
        <NavLink to="/professor" style={navStyle}>
          Professor
        </NavLink>
        <NavLink to="/student" style={navStyle}>
          Student
        </NavLink>
      </nav>

      <main style={styles.main}>
        <Outlet />
      </main>
    </div>
  )
}

function navStyle({ isActive }: { isActive: boolean }): React.CSSProperties {
  return {
    textDecoration: 'none',
    padding: '8px 14px',
    borderRadius: 6,
    color: isActive ? '#fff' : '#1a1a2e',
    background: isActive ? '#5c6ac4' : 'transparent',
    fontWeight: isActive ? 600 : 400,
    fontSize: '0.95rem',
  }
}

const styles: Record<string, React.CSSProperties> = {
  root: {
    minHeight: '100vh',
    fontFamily: 'system-ui, sans-serif',
  },
  nav: {
    display: 'flex',
    gap: 4,
    padding: '12px 24px',
    borderBottom: '1px solid #e0e0e0',
    background: '#f9f9fb',
    alignItems: 'center',
  },
  main: {
    padding: '0 8px',
  },
}

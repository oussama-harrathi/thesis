import React, { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useCourse } from '../../hooks/useCourses'
import {
  useCourseTopics,
  useCreateTopic,
  useUpdateTopic,
  useDeleteTopic,
} from '../../hooks/useTopics'
import type { Topic } from '../../types/api'

export default function TopicsPage() {
  const { courseId } = useParams<{ courseId: string }>()

  const { data: course } = useCourse(courseId)
  const {
    data: topics,
    isLoading,
    error,
  } = useCourseTopics(courseId)

  const createMutation = useCreateTopic(courseId ?? '')
  const updateMutation = useUpdateTopic(courseId ?? '')
  const deleteMutation = useDeleteTopic(courseId ?? '')

  // ── add form state ─────────────────────────────────────────────
  const [newName, setNewName] = useState('')

  // ── inline-edit state ──────────────────────────────────────────
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')

  // ── handlers ──────────────────────────────────────────────────
  function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = newName.trim()
    if (!trimmed) return
    createMutation.mutate(
      { name: trimmed },
      { onSuccess: () => setNewName('') },
    )
  }

  function startEdit(topic: Topic) {
    setEditingId(topic.id)
    setEditValue(topic.name)
  }

  function handleEditSave(topicId: string) {
    const trimmed = editValue.trim()
    if (!trimmed) return
    updateMutation.mutate(
      { topicId, body: { name: trimmed } },
      { onSuccess: () => setEditingId(null) },
    )
  }

  function handleDelete(topicId: string) {
    if (!window.confirm('Delete this topic?')) return
    deleteMutation.mutate(topicId)
  }

  // ── render ────────────────────────────────────────────────────
  return (
    <div style={s.container}>
      <p>
        <Link to={`/courses/${courseId}`} style={s.backLink}>
          ← {course ? course.name : 'Course'}
        </Link>
      </p>

      <h1 style={s.pageTitle}>Topics</h1>
      <p style={s.subtitle}>
        Topics are auto-extracted from uploaded course materials. You can add,
        rename, or remove them.
      </p>

      {/* Add topic form */}
      <form onSubmit={handleAdd} style={s.addForm}>
        <input
          style={s.input}
          placeholder="New topic name…"
          value={newName}
          onChange={e => setNewName(e.target.value)}
          disabled={createMutation.isPending}
        />
        <button
          type="submit"
          style={s.btnPrimary}
          disabled={createMutation.isPending || !newName.trim()}
        >
          {createMutation.isPending ? 'Adding…' : '+ Add Topic'}
        </button>
      </form>
      {createMutation.isError && (
        <p style={s.error}>Failed to add: {createMutation.error?.message}</p>
      )}

      {/* Topic list */}
      {isLoading && <p style={s.muted}>Loading topics…</p>}
      {error && <p style={s.error}>Failed to load topics: {error.message}</p>}

      {!isLoading && topics?.length === 0 && (
        <p style={s.muted}>
          No topics yet. Upload and process a PDF first, or add one manually.
        </p>
      )}

      {topics && topics.length > 0 && (
        <ul style={s.list}>
          {topics.map(topic => (
            <li key={topic.id} style={s.item}>
              {editingId === topic.id ? (
                /* ── edit row ── */
                <div style={s.editRow}>
                  <input
                    style={{ ...s.input, flex: 1 }}
                    value={editValue}
                    onChange={e => setEditValue(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') handleEditSave(topic.id)
                      if (e.key === 'Escape') setEditingId(null)
                    }}
                    autoFocus
                    disabled={updateMutation.isPending}
                  />
                  <button
                    style={s.btnPrimary}
                    onClick={() => handleEditSave(topic.id)}
                    disabled={updateMutation.isPending || !editValue.trim()}
                  >
                    Save
                  </button>
                  <button
                    style={s.btnGhost}
                    onClick={() => setEditingId(null)}
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                /* ── display row ── */
                <div style={s.displayRow}>
                  <span style={s.topicName}>{topic.name}</span>
                  <span style={{
                    ...s.badge,
                    color: topic.is_auto_extracted ? '#5c6ac4' : '#27ae60',
                  }}>
                    {topic.is_auto_extracted ? 'auto' : 'manual'}
                  </span>
                  <div style={s.actions}>
                    <button
                      style={s.btnGhost}
                      onClick={() => startEdit(topic)}
                    >
                      Rename
                    </button>
                    <button
                      style={{ ...s.btnGhost, color: '#c0392b' }}
                      onClick={() => handleDelete(topic.id)}
                      disabled={deleteMutation.isPending}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ── Styles ────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  container: {
    maxWidth: 720,
    margin: '40px auto',
    padding: '0 16px',
    fontFamily: 'system-ui, sans-serif',
  },
  backLink: { color: '#5c6ac4', textDecoration: 'none' },
  pageTitle: { margin: '8px 0 4px', fontSize: '1.6rem' },
  subtitle: { color: '#666', marginTop: 0, marginBottom: 24 },

  addForm: { display: 'flex', gap: 8, marginBottom: 8 },
  input: {
    flex: 1,
    padding: '8px 12px',
    border: '1px solid #d0d4e8',
    borderRadius: 6,
    fontSize: '0.95rem',
    outline: 'none',
  },
  btnPrimary: {
    padding: '8px 16px',
    background: '#5c6ac4',
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    cursor: 'pointer',
    fontWeight: 600,
    fontSize: '0.9rem',
    whiteSpace: 'nowrap',
  },
  btnGhost: {
    padding: '6px 12px',
    background: 'transparent',
    color: '#5c6ac4',
    border: '1px solid #d0d4e8',
    borderRadius: 6,
    cursor: 'pointer',
    fontSize: '0.85rem',
  },

  list: { listStyle: 'none', padding: 0, margin: 0 },
  item: {
    padding: '10px 14px',
    background: '#fff',
    border: '1px solid #e2e4f0',
    borderRadius: 8,
    marginBottom: 8,
  },
  displayRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    flexWrap: 'wrap',
  },
  editRow: { display: 'flex', alignItems: 'center', gap: 8 },
  topicName: { flex: 1, fontWeight: 500 },
  badge: {
    fontSize: '0.72rem',
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
    padding: '2px 6px',
    borderRadius: 4,
    background: '#f0f0f8',
  },
  actions: { display: 'flex', gap: 6, marginLeft: 'auto' },

  muted: { color: '#888', margin: 0 },
  error: {
    color: '#c0392b',
    background: '#fdf0ee',
    padding: '8px 12px',
    borderRadius: 6,
    margin: '8px 0',
  },
}

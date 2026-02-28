import React, { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useCourse } from '../../hooks/useCourses'
import {
  useCourseTopics,
  useCreateTopic,
  useUpdateTopic,
  useDeleteTopic,
  useReextractTopics,
} from '../../hooks/useTopics'
import type { Topic } from '../../types/api'

export default function TopicsPage() {
  const { courseId } = useParams<{ courseId: string }>()

  const { data: course } = useCourse(courseId)
  const {
    data: topicData,
    isLoading,
    error,
  } = useCourseTopics(courseId)

  const createMutation = useCreateTopic(courseId ?? '')
  const updateMutation = useUpdateTopic(courseId ?? '')
  const deleteMutation = useDeleteTopic(courseId ?? '')
  const reextractMutation = useReextractTopics(courseId ?? '')

  // ── form / edit state ──────────────────────────────────────────
  const [newName, setNewName] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')

  // ── hierarchy UI state ─────────────────────────────────────────
  const [showSections, setShowSections] = useState(false)
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())

  // ── derived data ───────────────────────────────────────────────
  const allTopics: Topic[] = topicData?.topics ?? []
  const meta = topicData?.extraction_meta

  const isTopLevel = (t: Topic) =>
    !t.parent_topic_id || t.level === 'CHAPTER' || t.level === 'PART'

  const topLevelTopics = allTopics.filter(isTopLevel)

  const childrenOf = (parentId: string) =>
    allTopics.filter(t => t.parent_topic_id === parentId)

  const hasChildren = (t: Topic) =>
    allTopics.some(c => c.parent_topic_id === t.id)

  // Build flat display list for the current view mode
  const displayTopics: Array<{ topic: Topic; indent: number }> = showSections
    ? allTopics.map(t => ({
        topic: t,
        indent:
          t.level === 'SUBSECTION' ? 2 :
          t.level === 'SECTION' ? 1 : 0,
      }))
    : topLevelTopics.flatMap(t => {
        const items: Array<{ topic: Topic; indent: number }> = [{ topic: t, indent: 0 }]
        if (expandedIds.has(t.id)) {
          items.push(...childrenOf(t.id).map(c => ({ topic: c, indent: 1 })))
        }
        return items
      })

  function toggleExpand(topicId: string) {
    setExpandedIds(prev => {
      const next = new Set(prev)
      if (next.has(topicId)) next.delete(topicId)
      else next.add(topicId)
      return next
    })
  }

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

      <div style={s.titleRow}>
        <div>
          <h1 style={s.pageTitle}>Topics</h1>
          <p style={s.subtitle}>
            Topics are auto-extracted from uploaded course materials. You can add,
            rename, or remove them.
          </p>
        </div>
        <button
          style={reextractMutation.isPending ? s.btnReextractPending : s.btnReextract}
          disabled={reextractMutation.isPending}
          onClick={() => {
            if (window.confirm(
              'Re-run topic extraction? This will replace all auto-extracted topics with fresh results from the new extraction pipeline.'
            )) {
              reextractMutation.mutate()
            }
          }}
        >
          {reextractMutation.isPending ? '⏳ Re-extracting…' : '🔄 Re-extract Topics'}
        </button>
      </div>

      {/* Low-confidence banner */}
      {meta?.is_low_confidence && (
        <div style={s.lowConfBanner}>
          ⚠️ Topics were extracted with <strong>low confidence</strong> (method:{' '}
          <strong>{meta.chosen_method}</strong>, confidence:{' '}
          <strong>{(meta.overall_confidence * 100).toFixed(0)}%</strong>, coverage:{' '}
          <strong>{(meta.coverage_ratio * 100).toFixed(0)}%</strong>).{' '}
          Consider uploading materials with clearer headings or re-extracting.
        </div>
      )}

      {reextractMutation.isError && (
        <p style={s.error}>Re-extraction failed: {(reextractMutation.error as Error)?.message}</p>
      )}
      {reextractMutation.isSuccess && (
        <p style={{ color: '#27ae60', marginBottom: 12, fontSize: '0.9rem' }}>
          ✓ Topics re-extracted successfully ({reextractMutation.data?.topics.length ?? 0} topics found).
        </p>
      )}

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

      {/* Section toggle */}
      {allTopics.length > 0 && (
        <div style={s.sectionToggleRow}>
          <span style={s.muted}>
            {showSections
              ? `Showing all ${allTopics.length} topics`
              : `Showing ${topLevelTopics.length} chapter${topLevelTopics.length !== 1 ? 's' : ''}`}
          </span>
          <button
            style={s.btnToggle}
            onClick={() => setShowSections(v => !v)}
          >
            {showSections ? 'Hide Sections' : 'Show Sections'}
          </button>
        </div>
      )}

      {/* Topic list */}
      {isLoading && <p style={s.muted}>Loading topics…</p>}
      {error && <p style={s.error}>Failed to load topics: {error.message}</p>}

      {!isLoading && allTopics.length === 0 && (
        <p style={s.muted}>
          No topics yet. Upload and process a PDF first, or add one manually.
        </p>
      )}

      {displayTopics.length > 0 && (
        <ul style={s.list}>
          {displayTopics.map(({ topic, indent }) => (
            <li
              key={topic.id}
              style={{
                ...s.item,
                marginLeft: indent * 24,
                opacity: topic.is_noisy_suspect ? 0.55 : 1,
                background: indent > 0 ? '#f8f9ff' : '#fff',
              }}
            >
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
                  {/* Expand/collapse chevron for chapters with children */}
                  {!showSections && isTopLevel(topic) && hasChildren(topic) && (
                    <button
                      style={s.btnChevron}
                      onClick={() => toggleExpand(topic.id)}
                      title={expandedIds.has(topic.id) ? 'Collapse sections' : 'Expand sections'}
                    >
                      {expandedIds.has(topic.id) ? '▾' : '▸'}
                    </button>
                  )}
                  {(!isTopLevel(topic) || (!showSections && !hasChildren(topic))) && (
                    <span style={{ width: 20, flexShrink: 0 }} />
                  )}

                  <span style={{
                    ...s.topicName,
                    fontWeight: isTopLevel(topic) ? 600 : 400,
                    fontSize: indent > 0 ? '0.88rem' : undefined,
                  }}>
                    {topic.name}
                  </span>

                  {topic.level && (
                    <span style={{ ...s.badge, color: _levelColor(topic.level) }}>
                      {topic.level.toLowerCase()}
                    </span>
                  )}
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

// ── Level badge colour helper ─────────────────────────────────────

function _levelColor(level: string): string {
  switch (level.toUpperCase()) {
    case 'CHAPTER': case 'PART': return '#8e44ad'
    case 'SECTION': return '#2980b9'
    case 'SUBSECTION': return '#16a085'
    default: return '#5c6ac4'
  }
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
  titleRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: 16,
    marginBottom: 0,
  },
  pageTitle: { margin: '8px 0 4px', fontSize: '1.6rem' },
  subtitle: { color: '#666', marginTop: 0, marginBottom: 24 },

  lowConfBanner: {
    background: '#fff8e6',
    border: '1px solid #f0c040',
    borderRadius: 8,
    padding: '10px 14px',
    marginBottom: 16,
    fontSize: '0.88rem',
    color: '#7a5c00',
    lineHeight: 1.5,
  },

  sectionToggleRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 10,
    marginTop: 4,
  },

  btnReextract: {
    marginTop: 10,
    padding: '8px 16px',
    background: '#f0f4ff',
    color: '#5c6ac4',
    border: '1px solid #c0c8f0',
    borderRadius: 6,
    cursor: 'pointer',
    fontWeight: 600,
    fontSize: '0.88rem',
    whiteSpace: 'nowrap',
  },
  btnReextractPending: {
    marginTop: 10,
    padding: '8px 16px',
    background: '#e8eaf6',
    color: '#9fa8da',
    border: '1px solid #c0c8f0',
    borderRadius: 6,
    cursor: 'not-allowed',
    fontWeight: 600,
    fontSize: '0.88rem',
    whiteSpace: 'nowrap',
  },
  btnToggle: {
    padding: '5px 12px',
    background: '#f0f4ff',
    color: '#5c6ac4',
    border: '1px solid #c0c8f0',
    borderRadius: 6,
    cursor: 'pointer',
    fontSize: '0.82rem',
    fontWeight: 600,
  },
  btnChevron: {
    background: 'transparent',
    border: 'none',
    cursor: 'pointer',
    color: '#5c6ac4',
    fontSize: '0.9rem',
    padding: '0 4px',
    width: 20,
    flexShrink: 0,
    lineHeight: 1,
  },

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

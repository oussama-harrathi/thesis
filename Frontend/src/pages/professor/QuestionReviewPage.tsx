/**
 * QuestionReviewPage  — /courses/:courseId/questions
 *
 * Professor workflow: review, filter, approve, reject, and edit generated
 * questions for a course.
 *
 * Server-side filters applied via query params: type, difficulty, status.
 * Bloom-level filter is applied client-side (backend list endpoint does not
 * expose a bloom filter).
 */

import React, { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useCourse } from '../../hooks/useCourses'
import {
  useCourseQuestions,
  useApproveQuestion,
  useRejectQuestion,
} from '../../hooks/useQuestions'
import type {
  QuestionListItem,
  QuestionType,
  Difficulty,
  QuestionStatus,
  BloomLevel,
} from '../../types/api'
import type { ListQuestionsParams } from '../../lib/api'
import QuestionDetailModal from '../../components/QuestionDetailModal'
import EditQuestionModal from '../../components/EditQuestionModal'
import { useQuestion } from '../../hooks/useQuestions'

// ── Constants ─────────────────────────────────────────────────────

const QUESTION_TYPES: { value: QuestionType | ''; label: string }[] = [
  { value: '', label: 'All Types' },
  { value: 'mcq', label: 'MCQ' },
  { value: 'true_false', label: 'True / False' },
  { value: 'short_answer', label: 'Short Answer' },
  { value: 'essay', label: 'Essay' },
]

const DIFFICULTIES: { value: Difficulty | ''; label: string }[] = [
  { value: '', label: 'All Difficulties' },
  { value: 'easy', label: 'Easy' },
  { value: 'medium', label: 'Medium' },
  { value: 'hard', label: 'Hard' },
]

const STATUSES: { value: QuestionStatus | ''; label: string }[] = [
  { value: '', label: 'All Statuses' },
  { value: 'draft', label: 'Draft' },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
]

const BLOOM_LEVELS: { value: BloomLevel | ''; label: string }[] = [
  { value: '', label: 'All Bloom Levels' },
  { value: 'remember', label: 'Remember' },
  { value: 'understand', label: 'Understand' },
  { value: 'apply', label: 'Apply' },
  { value: 'analyze', label: 'Analyze' },
  { value: 'evaluate', label: 'Evaluate' },
  { value: 'create', label: 'Create' },
]

const STATUS_STYLE: Record<QuestionStatus, React.CSSProperties> = {
  draft:    { background: '#fef3c7', color: '#92400e' },
  approved: { background: '#d1fae5', color: '#065f46' },
  rejected: { background: '#fee2e2', color: '#991b1b' },
}

const DIFFICULTY_COLOR: Record<Difficulty, string> = {
  easy: '#16a34a',
  medium: '#d97706',
  hard: '#dc2626',
}

const TYPE_LABEL: Record<QuestionType, string> = {
  mcq: 'MCQ',
  true_false: 'T/F',
  short_answer: 'Short',
  essay: 'Essay',
}

// ── Main page ─────────────────────────────────────────────────────

export default function QuestionReviewPage() {
  const { courseId } = useParams<{ courseId: string }>()

  const { data: course } = useCourse(courseId)

  // ── Server-side filter state ───────────────────────────────────
  const [typeFilter, setTypeFilter] = useState<QuestionType | ''>('')
  const [diffFilter, setDiffFilter] = useState<Difficulty | ''>('')
  const [statusFilter, setStatusFilter] = useState<QuestionStatus | ''>('')

  // ── Client-side filter state ───────────────────────────────────
  const [bloomFilter, setBloomFilter] = useState<BloomLevel | ''>('')

  const serverParams: ListQuestionsParams = {
    ...(typeFilter ? { type: typeFilter } : {}),
    ...(diffFilter ? { difficulty: diffFilter } : {}),
    ...(statusFilter ? { status: statusFilter } : {}),
    limit: 200,
  }

  const { data: questions, isLoading, error, refetch } = useCourseQuestions(courseId, serverParams)

  const approveMutation = useApproveQuestion(courseId ?? '')
  const rejectMutation = useRejectQuestion(courseId ?? '')

  // ── Modal state ───────────────────────────────────────────────
  const [detailId, setDetailId] = useState<string | null>(null)
  const [editId, setEditId] = useState<string | null>(null)

  // Pre-fetch edit target for the modal
  const { data: editQuestion } = useQuestion(editId)

  // ── Derived: apply client-side bloom filter ───────────────────
  const filteredQuestions: QuestionListItem[] = (questions ?? []).filter(q =>
    bloomFilter ? q.bloom_level === bloomFilter : true
  )

  // ── Stats ─────────────────────────────────────────────────────
  const stats = {
    total: filteredQuestions.length,
    draft: filteredQuestions.filter(q => q.status === 'draft').length,
    approved: filteredQuestions.filter(q => q.status === 'approved').length,
    rejected: filteredQuestions.filter(q => q.status === 'rejected').length,
  }

  // ── Quick approve/reject from table row ───────────────────────
  function handleQuickApprove(q: QuestionListItem) {
    if (q.status !== 'draft') return
    approveMutation.mutate(q.id)
  }

  function handleQuickReject(q: QuestionListItem) {
    if (q.status !== 'draft') return
    rejectMutation.mutate({ questionId: q.id })
  }

  const busy = approveMutation.isPending || rejectMutation.isPending

  // ── Render ────────────────────────────────────────────────────
  return (
    <div style={s.container}>
      {/* Breadcrumb */}
      <div style={s.breadcrumb}>
        <Link to="/courses" style={s.link}>Courses</Link>
        {' / '}
        <Link to={`/courses/${courseId}`} style={s.link}>
          {course?.name ?? courseId}
        </Link>
        {' / '}
        <span>Question Review</span>
      </div>

      <h1 style={s.pageTitle}>Question Review</h1>

      {/* Stats row */}
      <div style={s.statsRow}>
        <StatCard label="Total" value={stats.total} color="#5c6ac4" />
        <StatCard label="Draft" value={stats.draft} color="#92400e" />
        <StatCard label="Approved" value={stats.approved} color="#065f46" />
        <StatCard label="Rejected" value={stats.rejected} color="#991b1b" />
      </div>

      {/* Filters */}
      <div style={s.filterBar}>
        <select style={s.select} value={typeFilter} onChange={e => setTypeFilter(e.target.value as QuestionType | '')}>
          {QUESTION_TYPES.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <select style={s.select} value={diffFilter} onChange={e => setDiffFilter(e.target.value as Difficulty | '')}>
          {DIFFICULTIES.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <select style={s.select} value={statusFilter} onChange={e => setStatusFilter(e.target.value as QuestionStatus | '')}>
          {STATUSES.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <select style={s.select} value={bloomFilter} onChange={e => setBloomFilter(e.target.value as BloomLevel | '')}>
          {BLOOM_LEVELS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <button style={s.btnReset} onClick={() => {
          setTypeFilter(''); setDiffFilter(''); setStatusFilter(''); setBloomFilter('')
        }}>
          Reset
        </button>
        <button style={s.btnRefresh} onClick={() => refetch()}>
          ↻ Refresh
        </button>
      </div>

      {/* Error */}
      {error && (
        <p style={s.errorText}>Failed to load questions: {error.message}</p>
      )}

      {/* Table */}
      {isLoading && <p style={s.muted}>Loading questions…</p>}
      {!isLoading && filteredQuestions.length === 0 && (
        <div style={s.empty}>
          <p>No questions match the current filters.</p>
          {(typeFilter || diffFilter || statusFilter || bloomFilter) && (
            <p style={s.muted}>Try clearing some filters.</p>
          )}
        </div>
      )}

      {filteredQuestions.length > 0 && (
        <div style={s.tableWrapper}>
          <table style={s.table}>
            <thead>
              <tr>
                <th style={s.th}>Type</th>
                <th style={{ ...s.th, width: '40%' }}>Question</th>
                <th style={s.th}>Difficulty</th>
                <th style={s.th}>Bloom</th>
                <th style={s.th}>Status</th>
                <th style={s.th}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredQuestions.map(q => (
                <tr key={q.id} style={s.tr}>
                  <td style={s.td}>
                    <span style={s.typeBadge}>{TYPE_LABEL[q.type]}</span>
                  </td>
                  <td style={{ ...s.td, ...s.bodyCell }}>
                    <button
                      style={s.bodyBtn}
                      onClick={() => setDetailId(q.id)}
                      title="View full question"
                    >
                      {q.body.length > 110 ? q.body.slice(0, 110) + '…' : q.body}
                    </button>
                  </td>
                  <td style={s.td}>
                    <span style={{ color: DIFFICULTY_COLOR[q.difficulty], fontWeight: 600, fontSize: 13 }}>
                      {q.difficulty}
                    </span>
                  </td>
                  <td style={s.td}>
                    {q.bloom_level
                      ? <span style={s.bloomChip}>{q.bloom_level}</span>
                      : <span style={s.muted}>—</span>}
                  </td>
                  <td style={s.td}>
                    <span style={{ ...s.statusBadge, ...STATUS_STYLE[q.status] }}>
                      {q.status}
                    </span>
                  </td>
                  <td style={{ ...s.td, ...s.actionCell }}>
                    <button
                      style={s.btnView}
                      onClick={() => setDetailId(q.id)}
                      title="View details + sources"
                    >
                      View
                    </button>
                    <button
                      style={s.btnEdit}
                      onClick={() => setEditId(q.id)}
                      title="Edit question"
                    >
                      Edit
                    </button>
                    {q.status === 'draft' && (
                      <>
                        <button
                          style={s.btnApprove}
                          onClick={() => handleQuickApprove(q)}
                          disabled={busy}
                          title="Approve"
                        >
                          ✓
                        </button>
                        <button
                          style={s.btnReject}
                          onClick={() => handleQuickReject(q)}
                          disabled={busy}
                          title="Reject"
                        >
                          ✗
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Detail modal */}
      {detailId && (
        <QuestionDetailModal
          courseId={courseId ?? ''}
          questionId={detailId}
          onClose={() => setDetailId(null)}
          onEdit={() => { setEditId(detailId); setDetailId(null) }}
        />
      )}

      {/* Edit modal — only renders when full data is available */}
      {editId && editQuestion && (
        <EditQuestionModal
          courseId={courseId ?? ''}
          question={editQuestion}
          onClose={() => setEditId(null)}
        />
      )}
    </div>
  )
}

// ── Small sub-components ─────────────────────────────────────────

function StatCard({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={s.statCard}>
      <span style={{ ...s.statValue, color }}>{value}</span>
      <span style={s.statLabel}>{label}</span>
    </div>
  )
}

// ── Styles ────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  container: {
    maxWidth: 1100, margin: '36px auto', padding: '0 20px',
    fontFamily: 'system-ui, sans-serif',
  },
  breadcrumb: { fontSize: 13, color: '#6b7280', marginBottom: 16 },
  link: { color: '#5c6ac4', textDecoration: 'none' },
  pageTitle: { fontSize: 26, fontWeight: 700, color: '#1a1a1a', margin: '0 0 24px' },

  statsRow: { display: 'flex', gap: 16, marginBottom: 24, flexWrap: 'wrap' },
  statCard: {
    background: '#f9fafb', border: '1px solid #e5e7eb',
    borderRadius: 10, padding: '14px 24px',
    display: 'flex', flexDirection: 'column', alignItems: 'center',
    minWidth: 100,
  },
  statValue: { fontSize: 28, fontWeight: 700, lineHeight: 1 },
  statLabel: { fontSize: 12, color: '#6b7280', marginTop: 4, fontWeight: 500 },

  filterBar: { display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 18 },
  select: {
    padding: '7px 12px', borderRadius: 6, border: '1px solid #d1d5db',
    fontSize: 13, background: '#fff', cursor: 'pointer',
  },
  btnReset: {
    padding: '7px 14px', borderRadius: 6, border: '1px solid #d1d5db',
    background: '#fff', fontSize: 13, cursor: 'pointer', color: '#6b7280',
  },
  btnRefresh: {
    padding: '7px 14px', borderRadius: 6, border: '1px solid #d1d5db',
    background: '#f3f4f6', fontSize: 13, cursor: 'pointer', color: '#374151',
  },

  tableWrapper: { overflowX: 'auto' },
  table: { width: '100%', borderCollapse: 'collapse', fontSize: 14 },
  th: {
    textAlign: 'left', padding: '10px 14px',
    borderBottom: '2px solid #e5e7eb', fontWeight: 600,
    color: '#6b7280', fontSize: 12, textTransform: 'uppercase',
    letterSpacing: '0.04em', whiteSpace: 'nowrap',
  },
  tr: { borderBottom: '1px solid #f3f4f6' },
  td: { padding: '10px 14px', verticalAlign: 'top', color: '#374151' },

  typeBadge: {
    background: '#ede9fe', color: '#5b21b6',
    fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 20,
    whiteSpace: 'nowrap',
  },
  statusBadge: {
    fontSize: 12, fontWeight: 600, padding: '2px 10px', borderRadius: 20,
    whiteSpace: 'nowrap',
  },
  bloomChip: {
    background: '#fef3c7', color: '#78350f',
    fontSize: 11, padding: '2px 8px', borderRadius: 20,
  },

  bodyCell: { maxWidth: 400 },
  bodyBtn: {
    background: 'none', border: 'none', padding: 0, cursor: 'pointer',
    textAlign: 'left', color: '#1e40af', fontSize: 14, lineHeight: 1.5,
    textDecoration: 'underline dotted', fontFamily: 'system-ui, sans-serif',
  },
  actionCell: { whiteSpace: 'nowrap', display: 'flex', gap: 6, alignItems: 'center' },
  btnView: {
    padding: '4px 12px', borderRadius: 5,
    border: '1px solid #d1d5db', background: '#f9fafb',
    fontSize: 12, cursor: 'pointer', color: '#374151',
  },
  btnEdit: {
    padding: '4px 12px', borderRadius: 5,
    border: '1px solid #c7d2fe', background: '#eef2ff',
    fontSize: 12, cursor: 'pointer', color: '#3730a3',
  },
  btnApprove: {
    padding: '4px 10px', borderRadius: 5,
    border: '1px solid #6ee7b7', background: '#ecfdf5',
    fontSize: 13, cursor: 'pointer', color: '#065f46', fontWeight: 700,
  },
  btnReject: {
    padding: '4px 10px', borderRadius: 5,
    border: '1px solid #fca5a5', background: '#fff1f2',
    fontSize: 13, cursor: 'pointer', color: '#991b1b', fontWeight: 700,
  },
  empty: {
    padding: '40px 0', textAlign: 'center', color: '#6b7280', fontSize: 15,
  },
  muted: { color: '#9ca3af', fontSize: 13 },
  errorText: { color: '#dc2626', fontSize: 14 },
}

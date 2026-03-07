/**
 * QuestionReviewPage  — /courses/:courseId/questions
 *
 * Professor workflow: review, filter, approve, reject, and edit generated
 * questions for a course.
 *
 * Features:
 *  1. REJECTED questions auto-reset to REVIEWED when edited — Approve/Reject shown again.
 *  2. Questions grouped by Blueprint title.
 *  3. Replace a question in a blueprint with another approved same-type question.
 *  4. "Go to Exam Builder" button for quick navigation.
 *
 * Server-side filters applied via query params: type, difficulty, status.
 * Bloom-level filter is applied client-side (backend list endpoint does not
 * expose a bloom filter).
 */

import React, { useState, useMemo } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useCourse } from '../../hooks/useCourses'
import {
  useCourseQuestions,
  useApproveQuestion,
  useRejectQuestion,
  useReplacementCandidates,
  useReplaceInBlueprint,
} from '../../hooks/useQuestions'
import { useDeleteBlueprint } from '../../hooks/useBlueprints'
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
  { value: 'reviewed', label: 'Reviewed (edited)' },
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
  reviewed: { background: '#dbeafe', color: '#1e40af' },
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
  const navigate = useNavigate()

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
  const replaceMutation = useReplaceInBlueprint(courseId ?? '')
  const deleteBlueprintMutation = useDeleteBlueprint(courseId ?? '')

  // ── Modal state ───────────────────────────────────────────────
  const [detailId, setDetailId] = useState<string | null>(null)
  const [editId, setEditId] = useState<string | null>(null)

  // Inline delete-blueprint confirmation: stores the blueprint ID being confirmed
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  // Replace modal state: which question are we replacing?
  const [replaceTarget, setReplaceTarget] = useState<QuestionListItem | null>(null)

  // Pre-fetch edit target for the modal
  const { data: editQuestion } = useQuestion(editId)

  // ── Derived: apply client-side bloom filter ───────────────────
  const filteredQuestions: QuestionListItem[] = (questions ?? []).filter(q =>
    bloomFilter ? q.bloom_level === bloomFilter : true
  )

  // ── Group questions by blueprint ──────────────────────────────
  // Group into: { blueprintTitle → questions[] }, preserving insertion order.
  // Questions with no blueprint go into a 'No Blueprint' group.
  const groupedByBlueprint = useMemo(() => {
    const map = new Map<string, { title: string; id: string | null; questions: QuestionListItem[] }>()
    for (const q of filteredQuestions) {
      const key = q.blueprint_id ?? '__none__'
      const label = q.blueprint_title ?? 'No Blueprint'
      if (!map.has(key)) {
        map.set(key, { title: label, id: q.blueprint_id, questions: [] })
      }
      map.get(key)!.questions.push(q)
    }
    return [...map.values()]
  }, [filteredQuestions])

  // ── Stats ─────────────────────────────────────────────────────
  const stats = {
    total: filteredQuestions.length,
    draft: filteredQuestions.filter(q => q.status === 'draft').length,
    reviewed: filteredQuestions.filter(q => q.status === 'reviewed').length,
    approved: filteredQuestions.filter(q => q.status === 'approved').length,
    rejected: filteredQuestions.filter(q => q.status === 'rejected').length,
  }

  // ── Quick approve/reject from table row ───────────────────────
  function handleQuickApprove(q: QuestionListItem) {
    if (q.status !== 'draft' && q.status !== 'reviewed') return
    approveMutation.mutate(q.id)
  }

  function handleQuickReject(q: QuestionListItem) {
    if (q.status !== 'draft' && q.status !== 'reviewed') return
    rejectMutation.mutate({ questionId: q.id })
  }

  const busy = approveMutation.isPending || rejectMutation.isPending || replaceMutation.isPending

  function handleDeleteBlueprint(blueprintId: string) {
    deleteBlueprintMutation.mutate(blueprintId, {
      onSuccess: () => setConfirmDeleteId(null),
    })
  }

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

      {/* Header row with Go to Exam Builder */}
      <div style={s.headerRow}>
        <h1 style={s.pageTitle}>Question Review</h1>
        <button
          style={s.btnExamBuilder}
          onClick={() => navigate(`/courses/${courseId}/exam-builder`)}
          title="Go to Exam Builder"
        >
          Go to Exam Builder →
        </button>
      </div>

      {/* Stats row */}
      <div style={s.statsRow}>
        <StatCard label="Total" value={stats.total} color="#5c6ac4" />
        <StatCard label="Draft" value={stats.draft} color="#92400e" />
        <StatCard label="Reviewed" value={stats.reviewed} color="#1e40af" />
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

      {/* Table grouped by blueprint */}
      {isLoading && <p style={s.muted}>Loading questions…</p>}
      {!isLoading && filteredQuestions.length === 0 && (
        <div style={s.empty}>
          <p>No questions match the current filters.</p>
          {(typeFilter || diffFilter || statusFilter || bloomFilter) && (
            <p style={s.muted}>Try clearing some filters.</p>
          )}
        </div>
      )}

      {groupedByBlueprint.map(group => (
        <div key={group.id ?? '__none__'} style={s.group}>
          <div style={s.groupHeader}>
            <span style={s.groupTitle}>{group.title}</span>
            {/* Delete blueprint button — only for real blueprints */}
            {group.id && (
              confirmDeleteId === group.id ? (
                <span style={s.deleteConfirm}>
                  <span style={s.deleteConfirmText}>Delete blueprint + all questions?</span>
                  <button
                    style={s.btnDeleteConfirm}
                    onClick={() => handleDeleteBlueprint(group.id!)}
                    disabled={deleteBlueprintMutation.isPending}
                  >
                    {deleteBlueprintMutation.isPending ? 'Deleting…' : 'Yes, delete'}
                  </button>
                  <button
                    style={s.btnDeleteCancel}
                    onClick={() => setConfirmDeleteId(null)}
                    disabled={deleteBlueprintMutation.isPending}
                  >
                    Cancel
                  </button>
                </span>
              ) : (
                <button
                  style={s.btnDeleteBlueprint}
                  onClick={() => setConfirmDeleteId(group.id!)}
                  title="Delete this blueprint and all its questions"
                >
                  🗑
                </button>
              )
            )}
            <span style={s.groupCount}>{group.questions.length} question{group.questions.length !== 1 ? 's' : ''}</span>
          </div>
          <div style={s.tableWrapper}>
            <table style={s.table}>
              <thead>
                <tr>
                  <th style={s.th}>Type</th>
                  <th style={{ ...s.th, width: '38%' }}>Question</th>
                  <th style={s.th}>Difficulty</th>
                  <th style={s.th}>Bloom</th>
                  <th style={s.th}>Status</th>
                  <th style={s.th}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {group.questions.map(q => (
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
                      {/* Approve/Reject shown for draft AND reviewed (edited-rejected) */}
                      {(q.status === 'draft' || q.status === 'reviewed') && (
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
                      {/* Replace only available for questions with a blueprint mapping */}
                      {group.id && (
                        <button
                          style={s.btnReplace}
                          onClick={() => setReplaceTarget(q)}
                          title="Replace this question with another approved question"
                        >
                          ⇄
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}

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

      {/* Replace modal */}
      {replaceTarget && (
        <ReplaceQuestionModal
          courseId={courseId ?? ''}
          question={replaceTarget}
          onClose={() => setReplaceTarget(null)}
          onReplace={(replacementId) => {
            if (!replaceTarget.blueprint_id) return
            replaceMutation.mutate({
              blueprintId: replaceTarget.blueprint_id,
              questionId: replaceTarget.id,
              replacementQuestionId: replacementId,
            }, {
              onSuccess: () => setReplaceTarget(null),
            })
          }}
          isReplacing={replaceMutation.isPending}
          replaceError={replaceMutation.error?.message ?? null}
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

// ── Replace Question Modal ────────────────────────────────────────

interface ReplaceModalProps {
  courseId: string
  question: QuestionListItem
  onClose: () => void
  onReplace: (replacementId: string) => void
  isReplacing: boolean
  replaceError: string | null
}

function ReplaceQuestionModal({
  courseId,
  question,
  onClose,
  onReplace,
  isReplacing,
  replaceError,
}: ReplaceModalProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const { data: candidates, isLoading } = useReplacementCandidates(
    courseId,
    question.type,
    question.blueprint_id ?? undefined,
  )

  return (
    <div style={m.overlay} onClick={onClose}>
      <div style={m.modal} onClick={e => e.stopPropagation()}>
        <div style={m.header}>
          <h3 style={m.title}>Replace Question</h3>
          <button style={m.close} onClick={onClose}>✕</button>
        </div>

        <p style={m.hint}>
          Replacing <strong>{question.type.toUpperCase()}</strong> question from blueprint{' '}
          <em>{question.blueprint_title ?? '—'}</em>:<br />
          <span style={m.originalBody}>
            {question.body.length > 120 ? question.body.slice(0, 120) + '…' : question.body}
          </span>
        </p>

        {isLoading && <p style={m.info}>Loading candidates…</p>}
        {!isLoading && candidates?.length === 0 && (
          <p style={m.info}>No approved {question.type} questions from other blueprints.</p>
        )}

        {candidates && candidates.length > 0 && (
          <div style={m.candidateList}>
            {candidates.map(c => (
              <label key={c.id} style={{
                ...m.candidateRow,
                ...(selectedId === c.id ? m.candidateSelected : {}),
              }}>
                <input
                  type="radio"
                  name="replacement"
                  value={c.id}
                  checked={selectedId === c.id}
                  onChange={() => setSelectedId(c.id)}
                  style={{ marginRight: 10, flexShrink: 0 }}
                />
                <div style={m.candidateBody}>
                  <div style={m.candidateText}>
                    {c.body.length > 120 ? c.body.slice(0, 120) + '…' : c.body}
                  </div>
                  <div style={m.candidateMeta}>
                    <span style={{ ...m.diffBadge, color: DIFFICULTY_COLOR[c.difficulty] }}>
                      {c.difficulty}
                    </span>
                    {c.bloom_level && (
                      <span style={m.bloomBadge}>{c.bloom_level}</span>
                    )}
                    {c.blueprint_title && (
                      <span style={m.bpBadge}>from: {c.blueprint_title}</span>
                    )}
                  </div>
                </div>
              </label>
            ))}
          </div>
        )}

        {replaceError && <p style={m.error}>{replaceError}</p>}

        <div style={m.footer}>
          <button style={m.btnCancel} onClick={onClose} disabled={isReplacing}>
            Cancel
          </button>
          <button
            style={{ ...m.btnConfirm, opacity: !selectedId || isReplacing ? 0.5 : 1 }}
            onClick={() => selectedId && onReplace(selectedId)}
            disabled={!selectedId || isReplacing}
          >
            {isReplacing ? 'Replacing…' : 'Replace'}
          </button>
        </div>
      </div>
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

  headerRow: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    marginBottom: 24, flexWrap: 'wrap', gap: 12,
  },
  pageTitle: { fontSize: 26, fontWeight: 700, color: '#1a1a1a', margin: 0 },
  btnExamBuilder: {
    padding: '9px 18px', borderRadius: 7,
    border: '1px solid #5c6ac4', background: '#eef2ff',
    fontSize: 13, cursor: 'pointer', color: '#3730a3', fontWeight: 600,
  },

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

  // Blueprint groups
  group: { marginBottom: 32 },
  groupHeader: {
    display: 'flex', alignItems: 'center', gap: 10,
    padding: '8px 14px', background: '#f3f4f6',
    borderRadius: 8, marginBottom: 8,
    border: '1px solid #e5e7eb',
    flexWrap: 'wrap',
  },
  groupTitle: { fontWeight: 700, fontSize: 14, color: '#1a1a1a' },
  groupCount: { fontSize: 12, color: '#6b7280', marginLeft: 'auto' },
  btnDeleteBlueprint: {
    padding: '3px 8px', borderRadius: 5,
    border: '1px solid #fca5a5', background: '#fff1f2',
    fontSize: 13, cursor: 'pointer', color: '#991b1b', lineHeight: 1,
  },
  deleteConfirm: {
    display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
  },
  deleteConfirmText: { fontSize: 13, color: '#991b1b', fontWeight: 600 },
  btnDeleteConfirm: {
    padding: '3px 12px', borderRadius: 5,
    border: '1px solid #dc2626', background: '#dc2626',
    fontSize: 12, cursor: 'pointer', color: '#fff', fontWeight: 600,
  },
  btnDeleteCancel: {
    padding: '3px 10px', borderRadius: 5,
    border: '1px solid #d1d5db', background: '#fff',
    fontSize: 12, cursor: 'pointer', color: '#374151',
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
  btnReplace: {
    padding: '4px 10px', borderRadius: 5,
    border: '1px solid #d1d5db', background: '#f9fafb',
    fontSize: 14, cursor: 'pointer', color: '#374151',
  },
  empty: {
    padding: '40px 0', textAlign: 'center', color: '#6b7280', fontSize: 15,
  },
  muted: { color: '#9ca3af', fontSize: 13 },
  errorText: { color: '#dc2626', fontSize: 14 },
}

// ── Replace modal styles ──────────────────────────────────────────

const m: Record<string, React.CSSProperties> = {
  overlay: {
    position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
    zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center',
  },
  modal: {
    background: '#fff', borderRadius: 12, width: 640, maxWidth: '95vw',
    maxHeight: '85vh', display: 'flex', flexDirection: 'column',
    boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
    fontFamily: 'system-ui, sans-serif',
  },
  header: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '16px 20px', borderBottom: '1px solid #e5e7eb',
  },
  title: { margin: 0, fontSize: 18, fontWeight: 700, color: '#1a1a1a' },
  close: {
    background: 'none', border: 'none', cursor: 'pointer',
    fontSize: 18, color: '#6b7280', padding: '4px 8px',
  },
  hint: {
    padding: '12px 20px', fontSize: 13, color: '#374151',
    borderBottom: '1px solid #f3f4f6', margin: 0,
    lineHeight: 1.6,
  },
  originalBody: { color: '#6b7280', fontStyle: 'italic' },
  info: { padding: '16px 20px', color: '#6b7280', fontSize: 13, margin: 0 },
  candidateList: {
    overflowY: 'auto', flex: 1,
    padding: '8px 16px',
  },
  candidateRow: {
    display: 'flex', alignItems: 'flex-start', gap: 8,
    padding: '10px 12px', borderRadius: 8, cursor: 'pointer',
    marginBottom: 6, border: '1px solid #e5e7eb',
    background: '#fafafa',
  },
  candidateSelected: {
    border: '2px solid #5c6ac4', background: '#eef2ff',
  },
  candidateBody: { flex: 1, minWidth: 0 },
  candidateText: {
    fontSize: 13, color: '#1a1a1a', lineHeight: 1.5,
    wordBreak: 'break-word',
  },
  candidateMeta: {
    display: 'flex', gap: 6, marginTop: 4, flexWrap: 'wrap',
  },
  diffBadge: { fontSize: 11, fontWeight: 700 },
  bloomBadge: {
    fontSize: 11, padding: '1px 6px', borderRadius: 20,
    background: '#fef3c7', color: '#78350f',
  },
  bpBadge: {
    fontSize: 11, padding: '1px 6px', borderRadius: 20,
    background: '#f3f4f6', color: '#6b7280',
  },
  error: { color: '#dc2626', fontSize: 13, padding: '8px 20px', margin: 0 },
  footer: {
    display: 'flex', justifyContent: 'flex-end', gap: 10,
    padding: '14px 20px', borderTop: '1px solid #e5e7eb',
  },
  btnCancel: {
    padding: '8px 18px', borderRadius: 6,
    border: '1px solid #d1d5db', background: '#fff',
    fontSize: 13, cursor: 'pointer', color: '#374151',
  },
  btnConfirm: {
    padding: '8px 18px', borderRadius: 6,
    border: '1px solid #5c6ac4', background: '#5c6ac4',
    fontSize: 13, cursor: 'pointer', color: '#fff', fontWeight: 600,
  },
}

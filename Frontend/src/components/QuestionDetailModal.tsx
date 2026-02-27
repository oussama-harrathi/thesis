/**
 * QuestionDetailModal
 *
 * Read-only view of a question's full detail:
 *  • body, type, difficulty, bloom level, status
 *  • MCQ options (for MCQ type) or correct answer (for others)
 *  • explanation
 *  • source snippets (RAG grounding evidence)
 *
 * Also provides Approve / Reject action buttons.
 */

import React, { useState } from 'react'
import type { QuestionDetail } from '../types/api'
import { useQuestion, useApproveQuestion, useRejectQuestion } from '../hooks/useQuestions'

interface Props {
  courseId: string
  questionId: string
  onClose: () => void
  onEdit: () => void
}

const TYPE_LABEL: Record<string, string> = {
  mcq: 'MCQ',
  true_false: 'True / False',
  short_answer: 'Short Answer',
  essay: 'Essay',
}

const STATUS_COLOR: Record<string, React.CSSProperties> = {
  draft:    { background: '#fef3c7', color: '#92400e' },
  approved: { background: '#d1fae5', color: '#065f46' },
  rejected: { background: '#fee2e2', color: '#991b1b' },
}

const DIFFICULTY_COLOR: Record<string, string> = {
  easy: '#16a34a',
  medium: '#d97706',
  hard: '#dc2626',
}

export default function QuestionDetailModal({ courseId, questionId, onClose, onEdit }: Props) {
  const { data: question, isLoading, error } = useQuestion(questionId)
  const approveMutation = useApproveQuestion(courseId)
  const rejectMutation = useRejectQuestion(courseId)

  const [rejectMode, setRejectMode] = useState(false)
  const [rejectReason, setRejectReason] = useState('')

  function handleApprove() {
    approveMutation.mutate(questionId, { onSuccess: onClose })
  }

  function handleReject() {
    rejectMutation.mutate(
      { questionId, body: { reason: rejectReason.trim() || undefined } },
      { onSuccess: onClose },
    )
  }

  const busy = approveMutation.isPending || rejectMutation.isPending

  return (
    <div style={s.overlay} onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={s.modal} role="dialog" aria-modal="true">
        {/* Header */}
        <div style={s.header}>
          <h2 style={s.title}>Question Detail</h2>
          <button style={s.close} onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div style={s.body}>
          {isLoading && <p style={s.muted}>Loading…</p>}
          {error && <p style={s.errorText}>Failed to load: {error.message}</p>}

          {question && <QuestionContent
            question={question}
            onEdit={onEdit}
            onApprove={handleApprove}
            onRejectClick={() => setRejectMode(true)}
            rejectMode={rejectMode}
            rejectReason={rejectReason}
            onRejectReasonChange={setRejectReason}
            onRejectConfirm={handleReject}
            onRejectCancel={() => { setRejectMode(false); setRejectReason('') }}
            busy={busy}
            approveError={approveMutation.error?.message}
            rejectError={rejectMutation.error?.message}
          />}
        </div>
      </div>
    </div>
  )
}

// ── Inner component ───────────────────────────────────────────────

interface ContentProps {
  question: QuestionDetail
  onEdit: () => void
  onApprove: () => void
  onRejectClick: () => void
  rejectMode: boolean
  rejectReason: string
  onRejectReasonChange: (v: string) => void
  onRejectConfirm: () => void
  onRejectCancel: () => void
  busy: boolean
  approveError?: string
  rejectError?: string
}

function QuestionContent({
  question, onEdit,
  onApprove, onRejectClick,
  rejectMode, rejectReason, onRejectReasonChange, onRejectConfirm, onRejectCancel,
  busy, approveError, rejectError,
}: ContentProps) {
  return (
    <div>
      {/* Meta badges */}
      <div style={s.metaRow}>
        <span style={s.typeBadge}>{TYPE_LABEL[question.type] ?? question.type}</span>
        <span style={{ ...s.statusBadge, ...STATUS_COLOR[question.status] }}>
          {question.status}
        </span>
        <span style={{ ...s.diffBadge, color: DIFFICULTY_COLOR[question.difficulty] ?? '#555' }}>
          {question.difficulty}
        </span>
        {question.bloom_level && (
          <span style={s.bloomBadge}>{question.bloom_level}</span>
        )}
        {question.insufficient_context && (
          <span style={s.warnBadge}>⚠ insufficient context</span>
        )}
      </div>

      {/* Body */}
      <h3 style={s.questionBody}>{question.body}</h3>

      {/* MCQ options */}
      {question.type === 'mcq' && question.mcq_options.length > 0 && (
        <ul style={s.optionList}>
          {question.mcq_options.map(opt => (
            <li key={opt.id} style={{
              ...s.optionItem,
              ...(opt.is_correct ? s.optionCorrect : {}),
            }}>
              <strong style={s.optionLabel}>{opt.label}.</strong> {opt.text}
              {opt.is_correct && <span style={s.correctMark}> ✓</span>}
            </li>
          ))}
        </ul>
      )}

      {/* Correct answer for non-MCQ */}
      {question.type !== 'mcq' && question.correct_answer && (
        <div style={s.answerBlock}>
          <span style={s.answerLabel}>Answer: </span>
          <span>{question.correct_answer}</span>
        </div>
      )}

      {/* Explanation */}
      {question.explanation && (
        <div style={s.section}>
          <p style={s.sectionTitle}>Explanation</p>
          <p style={s.sectionText}>{question.explanation}</p>
        </div>
      )}

      {/* Source snippets */}
      {question.sources.length > 0 && (
        <div style={s.section}>
          <p style={s.sectionTitle}>Source Snippets ({question.sources.length})</p>
          {question.sources.map(src => (
            <blockquote key={src.id} style={s.snippet}>
              "{src.snippet}"
            </blockquote>
          ))}
        </div>
      )}

      {/* Metadata footer */}
      <div style={s.metaFooter}>
        {question.model_name && <span>Model: <code>{question.model_name}</code></span>}
        {question.prompt_version && <span>Prompt v{question.prompt_version}</span>}
        <span>Created {new Date(question.created_at).toLocaleString()}</span>
      </div>

      <hr style={s.divider} />

      {/* Action buttons — only for draft questions */}
      {question.status === 'draft' && !rejectMode && (
        <div style={s.actions}>
          <button style={s.btnEdit} onClick={onEdit} disabled={busy}>Edit</button>
          <div style={s.rightActions}>
            <button style={s.btnReject} onClick={onRejectClick} disabled={busy}>
              Reject
            </button>
            <button style={s.btnApprove} onClick={onApprove} disabled={busy}>
              {busy ? 'Saving…' : 'Approve'}
            </button>
          </div>
        </div>
      )}

      {/* Edit button for non-draft (still allow editing) */}
      {question.status !== 'draft' && (
        <div style={s.actions}>
          <button style={s.btnEdit} onClick={onEdit}>Edit</button>
        </div>
      )}

      {/* Reject confirmation inline */}
      {rejectMode && (
        <div style={s.rejectBox}>
          <label style={s.label}>Rejection reason (optional)</label>
          <textarea
            style={s.rejectTextarea}
            placeholder="Explain why this question is rejected…"
            value={rejectReason}
            onChange={e => onRejectReasonChange(e.target.value)}
            rows={3}
          />
          <div style={s.rejectActions}>
            <button style={s.btnSecondary} onClick={onRejectCancel} disabled={busy}>Cancel</button>
            <button style={s.btnReject} onClick={onRejectConfirm} disabled={busy}>
              {busy ? 'Rejecting…' : 'Confirm Reject'}
            </button>
          </div>
        </div>
      )}

      {approveError && <p style={s.errorText}>Approve failed: {approveError}</p>}
      {rejectError && <p style={s.errorText}>Reject failed: {rejectError}</p>}
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  overlay: {
    position: 'fixed', inset: 0,
    background: 'rgba(0,0,0,0.45)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    zIndex: 1000,
    padding: 16,
  },
  modal: {
    background: '#fff',
    borderRadius: 10,
    width: '100%',
    maxWidth: 700,
    maxHeight: '90vh',
    overflow: 'hidden',
    boxShadow: '0 12px 40px rgba(0,0,0,0.2)',
    display: 'flex',
    flexDirection: 'column',
  },
  header: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '18px 24px 12px',
    borderBottom: '1px solid #eee',
    flexShrink: 0,
  },
  title: { margin: 0, fontSize: 18, fontWeight: 600, color: '#1a1a1a' },
  close: {
    background: 'transparent', border: 'none', fontSize: 18,
    cursor: 'pointer', color: '#666', padding: '2px 6px',
  },
  body: { padding: '20px 24px', overflowY: 'auto', flex: 1 },

  metaRow: { display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 14 },
  typeBadge: {
    background: '#e0e7ff', color: '#3730a3',
    fontSize: 12, fontWeight: 600, padding: '2px 10px', borderRadius: 20,
  },
  statusBadge: {
    fontSize: 12, fontWeight: 600, padding: '2px 10px', borderRadius: 20,
  },
  diffBadge: { fontSize: 12, fontWeight: 600 },
  bloomBadge: {
    background: '#fef9c3', color: '#713f12',
    fontSize: 12, padding: '2px 10px', borderRadius: 20,
  },
  warnBadge: {
    background: '#fff7ed', color: '#9a3412',
    fontSize: 12, padding: '2px 10px', borderRadius: 20,
  },

  questionBody: {
    fontSize: 16, lineHeight: 1.6, margin: '0 0 16px',
    color: '#1a1a1a', fontWeight: 500,
  },

  optionList: { listStyle: 'none', padding: 0, margin: '0 0 16px', display: 'flex', flexDirection: 'column', gap: 6 },
  optionItem: {
    padding: '7px 12px', borderRadius: 6,
    border: '1px solid #e5e7eb', fontSize: 14,
  },
  optionCorrect: {
    background: '#ecfdf5', borderColor: '#6ee7b7',
  },
  optionLabel: { marginRight: 4, color: '#5c6ac4' },
  correctMark: { color: '#059669', fontWeight: 700 },

  answerBlock: {
    background: '#f0fdf4', border: '1px solid #bbf7d0',
    borderRadius: 6, padding: '8px 14px', fontSize: 14,
    marginBottom: 16,
  },
  answerLabel: { fontWeight: 600, color: '#15803d', marginRight: 6 },

  section: { marginBottom: 16 },
  sectionTitle: { fontWeight: 600, fontSize: 13, color: '#6b7280', margin: '0 0 6px' },
  sectionText: { fontSize: 14, color: '#374151', margin: 0, lineHeight: 1.6 },

  snippet: {
    borderLeft: '3px solid #93c5fd', paddingLeft: 12,
    margin: '0 0 8px', color: '#374151',
    fontSize: 13, lineHeight: 1.6, fontStyle: 'italic',
  },

  metaFooter: {
    display: 'flex', gap: 16, flexWrap: 'wrap',
    fontSize: 12, color: '#9ca3af', marginBottom: 12,
  },

  divider: { border: 'none', borderTop: '1px solid #f1f1f1', margin: '14px 0' },

  actions: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
  rightActions: { display: 'flex', gap: 10 },

  btnApprove: {
    background: '#059669', color: '#fff',
    border: 'none', borderRadius: 6,
    padding: '8px 20px', fontSize: 14, fontWeight: 600, cursor: 'pointer',
  },
  btnReject: {
    background: '#fff', color: '#dc2626',
    border: '1px solid #fca5a5', borderRadius: 6,
    padding: '8px 20px', fontSize: 14, fontWeight: 600, cursor: 'pointer',
  },
  btnEdit: {
    background: '#f3f4f6', color: '#374151',
    border: '1px solid #d1d5db', borderRadius: 6,
    padding: '8px 18px', fontSize: 14, cursor: 'pointer',
  },
  btnSecondary: {
    background: '#f3f4f6', color: '#374151',
    border: '1px solid #d1d5db', borderRadius: 6,
    padding: '8px 18px', fontSize: 14, cursor: 'pointer',
  },

  rejectBox: {
    background: '#fff5f5', border: '1px solid #fecaca',
    borderRadius: 8, padding: 16,
    display: 'flex', flexDirection: 'column', gap: 10,
  },
  label: { fontWeight: 600, fontSize: 13, color: '#444' },
  rejectTextarea: {
    width: '100%', padding: '8px 10px', borderRadius: 6,
    border: '1px solid #fca5a5', fontSize: 14, resize: 'vertical',
    boxSizing: 'border-box',
  },
  rejectActions: { display: 'flex', gap: 10, justifyContent: 'flex-end' },

  muted: { color: '#9ca3af', fontSize: 14 },
  errorText: { color: '#dc2626', fontSize: 13 },
}

/**
 * Exam Builder Page  — /courses/:courseId/exam-builder
 *
 * Professor workflow:
 *   1. Select a blueprint from the course's blueprint list
 *   2. View existing assembled exams for that blueprint
 *   3. Assemble a new exam (auto-collect approved questions)
 *   4. In the exam builder:
 *      - See ordered questions
 *      - Reorder with ↑ / ↓ buttons
 *      - Edit per-question points inline
 *      - Remove a question from the exam
 *      - Save reorder (sends PATCH /exams/{id}/questions/reorder)
 */

import React, { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { blueprintsApi } from '../../lib/api'
import {
  useAssembleExam,
  useExam,
  useExamsByBlueprint,
  useReorderExam,
  useRemoveExamQuestion,
} from '../../hooks/useExams'
import { useCourse } from '../../hooks/useCourses'
import type {
  BlueprintListItem,
} from '../../types/api'

// ── Helpers ───────────────────────────────────────────────────────

const TYPE_LABEL: Record<string, string> = {
  mcq: 'MCQ',
  true_false: 'T/F',
  short_answer: 'Short',
  essay: 'Essay',
}

const DIFF_COLOR: Record<string, string> = {
  easy: '#16a34a',
  medium: '#d97706',
  hard: '#dc2626',
}

// ── Main Page ─────────────────────────────────────────────────────

export default function ExamBuilderPage() {
  const { courseId } = useParams<{ courseId: string }>()
  const { data: course } = useCourse(courseId)

  // ── Blueprint selection state ────────────────────────────────
  const [selectedBlueprintId, setSelectedBlueprintId] = useState<string | null>(null)
  const [selectedExamId, setSelectedExamId] = useState<string | null>(null)

  const { data: blueprints, isLoading: bpLoading, error: bpError } = useQuery({
    queryKey: ['blueprints', 'course', courseId],
    queryFn: () => blueprintsApi.listByCourse(courseId!),
    enabled: Boolean(courseId),
    staleTime: 15_000,
  })

  // Auto-select first blueprint when loaded
  useEffect(() => {
    if (blueprints && blueprints.length > 0 && !selectedBlueprintId) {
      setSelectedBlueprintId(blueprints[0].id)
    }
  }, [blueprints]) // eslint-disable-line react-hooks/exhaustive-deps

  const selectedBlueprint = blueprints?.find(b => b.id === selectedBlueprintId) ?? null

  return (
    <div style={s.container}>
      {/* Breadcrumb */}
      <div style={s.breadcrumb}>
        <Link to="/courses" style={s.link}>Courses</Link>
        {' / '}
        <Link to={`/courses/${courseId}`} style={s.link}>{course?.name ?? courseId}</Link>
        {' / '}
        <span>Exam Builder</span>
      </div>

      <h1 style={s.pageTitle}>Exam Builder</h1>

      {/* Blueprint picker */}
      <section style={s.section}>
        <h2 style={s.sectionTitle}>Select Blueprint</h2>
        {bpLoading && <p style={s.muted}>Loading blueprints…</p>}
        {bpError && <p style={s.errorText}>Failed to load blueprints: {bpError.message}</p>}
        {blueprints && blueprints.length === 0 && (
          <p style={s.muted}>
            No blueprints found for this course.{' '}
            <Link to={`/courses/${courseId}`} style={s.link}>Upload course materials</Link> first.
          </p>
        )}
        {blueprints && blueprints.length > 0 && (
          <div style={s.blueprintList}>
            {blueprints.map(bp => (
              <button
                key={bp.id}
                style={{
                  ...s.blueprintCard,
                  ...(bp.id === selectedBlueprintId ? s.blueprintCardActive : {}),
                }}
                onClick={() => {
                  setSelectedBlueprintId(bp.id)
                  setSelectedExamId(null)
                }}
              >
                <span style={s.blueprintTitle}>{bp.title}</span>
                <span style={s.blueprintMeta}>
                  {bp.total_questions}q · {bp.total_points}pts
                  {bp.duration_minutes ? ` · ${bp.duration_minutes}min` : ''}
                </span>
              </button>
            ))}
          </div>
        )}
      </section>

      {/* Exam list + assembly for selected blueprint */}
      {selectedBlueprintId && (
        <ExamSection
          blueprintId={selectedBlueprintId}
          blueprint={selectedBlueprint}
          selectedExamId={selectedExamId}
          onSelectExam={setSelectedExamId}
        />
      )}
    </div>
  )
}

// ── Exam Section (for a selected blueprint) ───────────────────────

interface ExamSectionProps {
  blueprintId: string
  blueprint: BlueprintListItem | null
  selectedExamId: string | null
  onSelectExam: (id: string | null) => void
}

function ExamSection({ blueprintId, blueprint, selectedExamId, onSelectExam }: ExamSectionProps) {
  const { data: examList, isLoading, error } = useExamsByBlueprint(blueprintId)
  const assembleMutation = useAssembleExam(blueprintId)

  // Assemble form state
  const [showAssembleForm, setShowAssembleForm] = useState(false)
  const [examTitle, setExamTitle] = useState(
    blueprint ? `${blueprint.title} — Final Exam` : 'New Exam'
  )
  const [examDesc, setExamDesc] = useState('')
  const [defaultPoints, setDefaultPoints] = useState<string>('1')

  useEffect(() => {
    setExamTitle(blueprint ? `${blueprint.title} — Final Exam` : 'New Exam')
  }, [blueprint?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  function handleAssemble(e: React.FormEvent) {
    e.preventDefault()
    const pts = parseFloat(defaultPoints)
    assembleMutation.mutate(
      {
        title: examTitle.trim(),
        description: examDesc.trim() || undefined,
        default_points_per_question: isNaN(pts) || pts <= 0 ? undefined : pts,
      },
      {
        onSuccess: (exam) => {
          setShowAssembleForm(false)
          onSelectExam(exam.id)
        },
      }
    )
  }

  return (
    <>
      <section style={s.section}>
        <div style={s.sectionHeader}>
          <h2 style={s.sectionTitle}>Assemblies</h2>
          <button style={s.btnPrimary} onClick={() => setShowAssembleForm(v => !v)}>
            {showAssembleForm ? 'Cancel' : '+ Assemble Exam'}
          </button>
        </div>

        {/* Assemble form */}
        {showAssembleForm && (
          <form onSubmit={handleAssemble} style={s.assembleForm}>
            <p style={s.formHint}>
              Collects all <strong>approved</strong> questions from this course
              (filtered to this blueprint's question set) and creates an exam.
            </p>
            <div style={s.formRow}>
              <div style={s.formCol}>
                <label style={s.label}>Exam Title *</label>
                <input
                  style={s.input}
                  value={examTitle}
                  onChange={e => setExamTitle(e.target.value)}
                  required
                />
              </div>
              <div style={s.formCol}>
                <label style={s.label}>Points Per Question</label>
                <input
                  style={s.input}
                  type="number"
                  min="0.5"
                  step="0.5"
                  value={defaultPoints}
                  onChange={e => setDefaultPoints(e.target.value)}
                  placeholder="e.g. 1"
                />
              </div>
            </div>
            <label style={s.label}>Description (optional)</label>
            <input
              style={s.input}
              value={examDesc}
              onChange={e => setExamDesc(e.target.value)}
              placeholder="Exam instructions or notes…"
            />
            {assembleMutation.isError && (
              <p style={s.errorText}>Assembly failed: {assembleMutation.error?.message}</p>
            )}
            <div style={{ textAlign: 'right', marginTop: 6 }}>
              <button
                type="submit"
                style={s.btnPrimary}
                disabled={assembleMutation.isPending || !examTitle.trim()}
              >
                {assembleMutation.isPending ? 'Assembling…' : 'Assemble'}
              </button>
            </div>
          </form>
        )}

        {isLoading && <p style={s.muted}>Loading exams…</p>}
        {error && <p style={s.errorText}>Failed to load exams: {error.message}</p>}
        {!isLoading && examList && examList.length === 0 && !showAssembleForm && (
          <p style={s.muted}>No exams assembled yet. Click "Assemble Exam" to create one.</p>
        )}
        {examList && examList.length > 0 && (
          <div style={s.examCardList}>
            {examList.map(exam => (
              <div
                key={exam.id}
                style={{
                  ...s.examCard,
                  ...(exam.id === selectedExamId ? s.examCardActive : {}),
                }}
                onClick={() => onSelectExam(exam.id === selectedExamId ? null : exam.id)}
              >
                <div style={s.examCardTitle}>{exam.title}</div>
                <div style={s.examCardMeta}>
                  {exam.question_count} questions
                  {exam.total_points ? ` · ${exam.total_points} pts` : ''}
                  <span style={s.examCardDate}>
                    {new Date(exam.created_at).toLocaleDateString()}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Exam builder table for the selected exam */}
      {selectedExamId && (
        <>
          <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'flex-end' }}>
            <Link
              to={`/exams/${selectedExamId}/export`}
              style={{
                background: '#4f46e5',
                color: '#fff',
                borderRadius: 8,
                padding: '7px 16px',
                fontSize: 13,
                fontWeight: 600,
                textDecoration: 'none',
              }}
            >
              📤 Export Exam →
            </Link>
          </div>
          <ExamBuilderTable examId={selectedExamId} />
        </>
      )}
    </>
  )
}

// ── Exam Builder Table ────────────────────────────────────────────

interface ExamBuilderTableProps {
  examId: string
}

function ExamBuilderTable({ examId }: ExamBuilderTableProps) {
  const { data: exam, isLoading, error } = useExam(examId)
  const reorderMutation = useReorderExam(examId)
  const removeMutation = useRemoveExamQuestion(examId)

  // Local working copy of questions for reorder + points edits
  const [localItems, setLocalItems] = useState<
    { eqId: string; position: number; points: string; body: string; type: string; difficulty: string }[]
  >([])
  const [isDirty, setIsDirty] = useState(false)

  // Sync local state when exam data arrives or changes
  useEffect(() => {
    if (!exam) return
    setLocalItems(
      [...exam.exam_questions]
        .sort((a, b) => a.position - b.position)
        .map((eq, i) => ({
          eqId: eq.id,
          position: i + 1,
          points: eq.points != null ? String(eq.points) : '',
          body: eq.question.body,
          type: eq.question.type,
          difficulty: eq.question.difficulty,
        }))
    )
    setIsDirty(false)
  }, [exam?.id, exam?.updated_at]) // eslint-disable-line react-hooks/exhaustive-deps

  function move(index: number, direction: -1 | 1) {
    const target = index + direction
    if (target < 0 || target >= localItems.length) return
    const updated = [...localItems]
    ;[updated[index], updated[target]] = [updated[target], updated[index]]
    setLocalItems(updated.map((item, i) => ({ ...item, position: i + 1 })))
    setIsDirty(true)
  }

  function setPoints(index: number, value: string) {
    setLocalItems(prev => prev.map((item, i) => i === index ? { ...item, points: value } : item))
    setIsDirty(true)
  }

  function handleSave() {
    reorderMutation.mutate({
      items: localItems.map(item => {
        const pts = parseFloat(item.points)
        return {
          exam_question_id: item.eqId,
          position: item.position,
          ...(isNaN(pts) || pts <= 0 ? {} : { points: pts }),
        }
      }),
    }, { onSuccess: () => setIsDirty(false) })
  }

  function handleRemove(eqId: string) {
    if (!window.confirm('Remove this question from the exam?')) return
    removeMutation.mutate(eqId)
  }

  if (isLoading) return <p style={s.muted}>Loading exam…</p>
  if (error) return <p style={s.errorText}>Failed to load exam: {error.message}</p>
  if (!exam) return null

  const totalPts = localItems.reduce((sum, item) => {
    const pts = parseFloat(item.points)
    return sum + (isNaN(pts) ? 0 : pts)
  }, 0)

  return (
    <section style={s.section}>
      {/* Exam header */}
      <div style={s.builderHeader}>
        <div>
          <h2 style={s.sectionTitle}>{exam.title}</h2>
          {exam.description && <p style={s.muted}>{exam.description}</p>}
        </div>
        <div style={s.builderStats}>
          <span style={s.statChip}>{localItems.length} questions</span>
          {totalPts > 0 && <span style={s.statChip}>{totalPts.toFixed(1)} pts total</span>}
          {isDirty && (
            <button
              style={s.btnSave}
              onClick={handleSave}
              disabled={reorderMutation.isPending}
            >
              {reorderMutation.isPending ? 'Saving…' : '💾 Save Order & Points'}
            </button>
          )}
        </div>
      </div>

      {reorderMutation.isError && (
        <p style={s.errorText}>Save failed: {reorderMutation.error?.message}</p>
      )}

      {localItems.length === 0 && (
        <p style={s.muted}>This exam has no questions yet.</p>
      )}

      {localItems.length > 0 && (
        <div style={s.tableWrapper}>
          <table style={s.table}>
            <thead>
              <tr>
                <th style={{ ...s.th, width: 40 }}>#</th>
                <th style={{ ...s.th, width: '42%' }}>Question</th>
                <th style={s.th}>Type</th>
                <th style={s.th}>Difficulty</th>
                <th style={{ ...s.th, width: 90 }}>Points</th>
                <th style={{ ...s.th, width: 110 }}>Move</th>
                <th style={{ ...s.th, width: 70 }}></th>
              </tr>
            </thead>
            <tbody>
              {localItems.map((item, idx) => (
                <tr key={item.eqId} style={s.tr}>
                  <td style={{ ...s.td, ...s.posCell }}>{item.position}</td>
                  <td style={{ ...s.td, ...s.bodyCell }}>
                    {item.body.length > 120 ? item.body.slice(0, 120) + '…' : item.body}
                  </td>
                  <td style={s.td}>
                    <span style={s.typeBadge}>{TYPE_LABEL[item.type] ?? item.type}</span>
                  </td>
                  <td style={s.td}>
                    <span style={{ color: DIFF_COLOR[item.difficulty] ?? '#555', fontWeight: 600, fontSize: 13 }}>
                      {item.difficulty}
                    </span>
                  </td>
                  <td style={s.td}>
                    <input
                      type="number"
                      min="0.5"
                      step="0.5"
                      style={s.pointsInput}
                      value={item.points}
                      onChange={e => setPoints(idx, e.target.value)}
                      placeholder="—"
                    />
                  </td>
                  <td style={{ ...s.td, whiteSpace: 'nowrap' }}>
                    <button
                      style={s.moveBtn}
                      onClick={() => move(idx, -1)}
                      disabled={idx === 0}
                      title="Move up"
                    >↑</button>
                    <button
                      style={s.moveBtn}
                      onClick={() => move(idx, 1)}
                      disabled={idx === localItems.length - 1}
                      title="Move down"
                    >↓</button>
                  </td>
                  <td style={s.td}>
                    <button
                      style={s.removeBtn}
                      onClick={() => handleRemove(item.eqId)}
                      disabled={removeMutation.isPending}
                      title="Remove from exam"
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
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
  pageTitle: { fontSize: 26, fontWeight: 700, color: '#1a1a1a', margin: '0 0 28px' },

  section: {
    background: '#fff', border: '1px solid #e5e7eb',
    borderRadius: 10, padding: '20px 24px', marginBottom: 24,
    boxShadow: '0 1px 4px rgba(0,0,0,0.05)',
  },
  sectionHeader: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    marginBottom: 16,
  },
  sectionTitle: { fontSize: 17, fontWeight: 700, color: '#111827', margin: '0 0 14px' },

  blueprintList: { display: 'flex', flexWrap: 'wrap', gap: 12 },
  blueprintCard: {
    background: '#f9fafb', border: '2px solid #e5e7eb',
    borderRadius: 8, padding: '12px 18px',
    cursor: 'pointer', textAlign: 'left',
    display: 'flex', flexDirection: 'column', gap: 4,
    minWidth: 200,
  },
  blueprintCardActive: {
    border: '2px solid #5c6ac4', background: '#eef2ff',
  },
  blueprintTitle: { fontWeight: 600, fontSize: 14, color: '#111827' },
  blueprintMeta: { fontSize: 12, color: '#6b7280' },

  assembleForm: {
    background: '#f8faff', border: '1px solid #c7d2fe',
    borderRadius: 8, padding: '16px 20px', marginBottom: 16,
    display: 'flex', flexDirection: 'column', gap: 12,
  },
  formHint: { fontSize: 13, color: '#6b7280', margin: 0 },
  formRow: { display: 'flex', gap: 16 },
  formCol: { flex: 1, display: 'flex', flexDirection: 'column', gap: 4 },
  label: { fontWeight: 600, fontSize: 13, color: '#374151' },
  input: {
    padding: '8px 10px', borderRadius: 6, border: '1px solid #d1d5db',
    fontSize: 14, boxSizing: 'border-box' as const, width: '100%',
  },

  examCardList: { display: 'flex', flexDirection: 'column', gap: 10, marginTop: 6 },
  examCard: {
    background: '#f9fafb', border: '1px solid #e5e7eb',
    borderRadius: 8, padding: '12px 18px', cursor: 'pointer',
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  },
  examCardActive: { background: '#eff6ff', border: '1px solid #93c5fd' },
  examCardTitle: { fontWeight: 600, fontSize: 14, color: '#111827' },
  examCardMeta: { fontSize: 13, color: '#6b7280', display: 'flex', gap: 8, alignItems: 'center' },
  examCardDate: { fontSize: 12, color: '#9ca3af', marginLeft: 8 },

  builderHeader: {
    display: 'flex', justifyContent: 'space-between',
    alignItems: 'flex-start', marginBottom: 18,
  },
  builderStats: { display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' },
  statChip: {
    background: '#e0e7ff', color: '#3730a3',
    fontSize: 12, fontWeight: 600, padding: '3px 12px', borderRadius: 20,
  },

  tableWrapper: { overflowX: 'auto' },
  table: { width: '100%', borderCollapse: 'collapse', fontSize: 14 },
  th: {
    textAlign: 'left', padding: '9px 12px',
    borderBottom: '2px solid #e5e7eb',
    fontWeight: 600, color: '#6b7280',
    fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.04em',
    whiteSpace: 'nowrap',
  },
  tr: { borderBottom: '1px solid #f3f4f6' },
  td: { padding: '9px 12px', verticalAlign: 'middle', color: '#374151' },
  posCell: { fontWeight: 700, color: '#9ca3af', width: 40 },
  bodyCell: { color: '#1e40af', fontSize: 13 },
  typeBadge: {
    background: '#ede9fe', color: '#5b21b6',
    fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 20,
    whiteSpace: 'nowrap',
  },
  pointsInput: {
    width: 72, padding: '5px 8px', borderRadius: 5,
    border: '1px solid #d1d5db', fontSize: 13,
    textAlign: 'right' as const,
  },
  moveBtn: {
    background: '#f3f4f6', border: '1px solid #d1d5db',
    borderRadius: 4, padding: '3px 10px',
    fontSize: 14, cursor: 'pointer', marginRight: 4,
    color: '#374151',
  },
  removeBtn: {
    background: '#fff1f2', border: '1px solid #fca5a5',
    borderRadius: 4, padding: '3px 8px',
    fontSize: 13, cursor: 'pointer', color: '#dc2626', fontWeight: 700,
  },
  btnPrimary: {
    background: '#5c6ac4', color: '#fff',
    border: 'none', borderRadius: 6,
    padding: '8px 18px', fontSize: 14, fontWeight: 600, cursor: 'pointer',
  },
  btnSave: {
    background: '#059669', color: '#fff',
    border: 'none', borderRadius: 6,
    padding: '8px 18px', fontSize: 14, fontWeight: 600, cursor: 'pointer',
  },
  muted: { color: '#9ca3af', fontSize: 14, margin: '8px 0' },
  errorText: { color: '#dc2626', fontSize: 14 },
}

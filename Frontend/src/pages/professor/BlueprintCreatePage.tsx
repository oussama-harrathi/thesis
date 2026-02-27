/**
 * BlueprintCreatePage  — /courses/:courseId/blueprints/new
 *
 * Professor workflow step 2:
 *   Fill in blueprint details → Create → Generate Questions
 *
 * After creation the professor can immediately trigger question generation,
 * which dispatches a Celery job and redirects to the GenerationPage.
 */

import React, { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useCourse } from '../../hooks/useCourses'
import { useCreateBlueprint, useGenerateFromBlueprint } from '../../hooks/useBlueprints'
import type { BlueprintConfig } from '../../types/api'

export default function BlueprintCreatePage() {
  const { courseId } = useParams<{ courseId: string }>()
  const navigate = useNavigate()
  const { data: course } = useCourse(courseId)

  const createMutation = useCreateBlueprint(courseId ?? '')
  const generateMutation = useGenerateFromBlueprint()

  // ── Form state ────────────────────────────────────────────────
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')

  // Question counts
  const [mcq, setMcq] = useState(5)
  const [trueFalse, setTrueFalse] = useState(3)
  const [shortAnswer, setShortAnswer] = useState(2)
  const [essay, setEssay] = useState(0)

  // Difficulty mix (as percentages, must sum to 100)
  const [easy, setEasy] = useState(34)
  const [medium, setMedium] = useState(33)
  const [hard, setHard] = useState(33)

  // Extras
  const [totalPoints, setTotalPoints] = useState(100)
  const [duration, setDuration] = useState<number | ''>('')

  const [error, setError] = useState<string | null>(null)
  const [createdBlueprintId, setCreatedBlueprintId] = useState<string | null>(null)

  // ── Derived ───────────────────────────────────────────────────
  const totalQuestions = mcq + trueFalse + shortAnswer + essay
  const difficultySum = easy + medium + hard

  // ── Submit: create blueprint ──────────────────────────────────
  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)

    if (!title.trim()) { setError('Title is required.'); return }
    if (totalQuestions < 1) { setError('At least one question is required.'); return }
    if (difficultySum !== 100) {
      setError(`Difficulty percentages must sum to 100 (currently ${difficultySum}).`)
      return
    }

    const config: BlueprintConfig = {
      question_counts: { mcq, true_false: trueFalse, short_answer: shortAnswer, essay },
      difficulty_mix: { easy: easy / 100, medium: medium / 100, hard: hard / 100 },
      bloom_mix: null,
      topic_mix: { mode: 'auto', topics: [] },
      total_points: totalPoints,
      duration_minutes: duration === '' ? null : Number(duration),
    }

    createMutation.mutate(
      { title: title.trim(), description: description.trim() || undefined, config },
      {
        onSuccess: (bp) => setCreatedBlueprintId(bp.id),
        onError: (err) => setError(err.message),
      },
    )
  }

  // ── Generate: dispatch Celery job ─────────────────────────────
  function handleGenerate() {
    if (!createdBlueprintId) return
    setError(null)
    generateMutation.mutate(createdBlueprintId, {
      onSuccess: (resp) => {
        navigate(`/courses/${courseId}/generation/${resp.job_id}`, {
          state: { questionSetId: resp.question_set_id },
        })
      },
      onError: (err) => setError(err.message),
    })
  }

  // ── Render ────────────────────────────────────────────────────
  return (
    <div style={s.container}>
      <p>
        <Link to={`/courses/${courseId}`} style={s.back}>
          ← {course?.name ?? 'Course'}
        </Link>
      </p>
      <h1 style={s.heading}>Create Exam Blueprint</h1>
      <p style={s.subtitle}>
        Define how many questions of each type to generate and the difficulty
        distribution. Questions will be generated from your uploaded course materials.
      </p>

      {/* ── After creation: generate CTA ── */}
      {createdBlueprintId && (
        <div style={s.successBox}>
          <strong>✅ Blueprint created!</strong>
          <p style={{ margin: '8px 0 0' }}>
            Ready to generate {totalQuestions} questions from your course materials.
          </p>
          <button
            style={s.btnGenerate}
            onClick={handleGenerate}
            disabled={generateMutation.isPending}
          >
            {generateMutation.isPending ? '⏳ Dispatching…' : '🚀 Generate Questions'}
          </button>
          <span style={s.orLink}>
            or{' '}
            <Link to={`/courses/${courseId}/blueprints/new`} onClick={() => window.location.reload()}>
              create another blueprint
            </Link>
          </span>
        </div>
      )}

      {/* ── Creation form (hidden after created) ── */}
      {!createdBlueprintId && (
        <form onSubmit={handleSubmit} style={s.form}>
          {/* Title */}
          <div style={s.field}>
            <label style={s.label}>Blueprint Title *</label>
            <input
              style={s.input}
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder="e.g. Midterm Exam 2026"
            />
          </div>

          {/* Description */}
          <div style={s.field}>
            <label style={s.label}>Description (optional)</label>
            <input
              style={s.input}
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Brief notes about this exam"
            />
          </div>

          {/* Question Counts */}
          <fieldset style={s.fieldset}>
            <legend style={s.legend}>Question Counts</legend>
            <div style={s.row}>
              {[
                { label: 'MCQ', value: mcq, set: setMcq },
                { label: 'True / False', value: trueFalse, set: setTrueFalse },
                { label: 'Short Answer', value: shortAnswer, set: setShortAnswer },
                { label: 'Essay', value: essay, set: setEssay },
              ].map(({ label, value, set }) => (
                <div key={label} style={s.countField}>
                  <label style={s.smallLabel}>{label}</label>
                  <input
                    type="number"
                    min={0}
                    max={50}
                    style={s.numInput}
                    value={value}
                    onChange={e => set(Math.max(0, parseInt(e.target.value) || 0))}
                  />
                </div>
              ))}
            </div>
            <p style={s.hint}>Total: <strong>{totalQuestions}</strong> questions</p>
          </fieldset>

          {/* Difficulty Mix */}
          <fieldset style={s.fieldset}>
            <legend style={s.legend}>Difficulty Mix (must sum to 100%)</legend>
            <div style={s.row}>
              {[
                { label: '🟢 Easy %', value: easy, set: setEasy, color: '#16a34a' },
                { label: '🟡 Medium %', value: medium, set: setMedium, color: '#d97706' },
                { label: '🔴 Hard %', value: hard, set: setHard, color: '#dc2626' },
              ].map(({ label, value, set, color }) => (
                <div key={label} style={s.countField}>
                  <label style={{ ...s.smallLabel, color }}>{label}</label>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    style={s.numInput}
                    value={value}
                    onChange={e => set(Math.max(0, Math.min(100, parseInt(e.target.value) || 0)))}
                  />
                </div>
              ))}
            </div>
            <p style={{ ...s.hint, color: difficultySum !== 100 ? '#dc2626' : '#16a34a' }}>
              Sum: <strong>{difficultySum}%</strong>
              {difficultySum !== 100 && ' ← must be 100'}
            </p>
          </fieldset>

          {/* Totals */}
          <div style={s.row}>
            <div style={s.field}>
              <label style={s.label}>Total Points</label>
              <input
                type="number"
                min={1}
                style={s.numInput}
                value={totalPoints}
                onChange={e => setTotalPoints(Math.max(1, parseInt(e.target.value) || 1))}
              />
            </div>
            <div style={s.field}>
              <label style={s.label}>Duration (minutes, optional)</label>
              <input
                type="number"
                min={5}
                style={s.numInput}
                value={duration}
                placeholder="—"
                onChange={e => setDuration(e.target.value === '' ? '' : Math.max(5, parseInt(e.target.value) || 5))}
              />
            </div>
          </div>

          {error && <p style={s.error}>{error}</p>}

          <div style={{ marginTop: 24 }}>
            <button
              type="submit"
              style={s.btnPrimary}
              disabled={createMutation.isPending}
            >
              {createMutation.isPending ? 'Creating…' : '📐 Create Blueprint'}
            </button>
          </div>
        </form>
      )}

      {error && createdBlueprintId && <p style={s.error}>{error}</p>}
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  container: { maxWidth: 700, margin: '40px auto', padding: '0 16px', fontFamily: 'system-ui, sans-serif' },
  back: { color: '#5c6ac4', textDecoration: 'none' },
  heading: { margin: '8px 0 4px' },
  subtitle: { color: '#666', marginBottom: 28 },
  form: { display: 'flex', flexDirection: 'column', gap: 20 },
  field: { display: 'flex', flexDirection: 'column', gap: 6 },
  label: { fontWeight: 600, fontSize: '0.9rem' },
  smallLabel: { fontWeight: 600, fontSize: '0.82rem', marginBottom: 4 },
  input: { padding: '8px 12px', border: '1px solid #ccc', borderRadius: 6, fontSize: '0.95rem', width: '100%', boxSizing: 'border-box' },
  numInput: { padding: '8px 12px', border: '1px solid #ccc', borderRadius: 6, fontSize: '0.95rem', width: 90 },
  fieldset: { border: '1px solid #e0e0e0', borderRadius: 8, padding: '16px 20px' },
  legend: { fontWeight: 700, fontSize: '0.9rem', padding: '0 6px' },
  row: { display: 'flex', gap: 24, flexWrap: 'wrap', alignItems: 'flex-end' },
  countField: { display: 'flex', flexDirection: 'column' },
  hint: { margin: '10px 0 0', fontSize: '0.85rem', color: '#555' },
  btnPrimary: { padding: '10px 24px', background: '#5c6ac4', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontWeight: 600, fontSize: '0.95rem' },
  btnGenerate: { display: 'block', marginTop: 14, padding: '12px 28px', background: '#16a34a', color: '#fff', border: 'none', borderRadius: 8, cursor: 'pointer', fontWeight: 700, fontSize: '1rem' },
  successBox: { background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 10, padding: '20px 24px', marginBottom: 24 },
  orLink: { display: 'block', marginTop: 12, fontSize: '0.88rem', color: '#555' },
  error: { color: '#dc2626', fontWeight: 500, margin: '4px 0' },
}

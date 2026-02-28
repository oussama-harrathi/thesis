/**
 * PracticeCreatePage
 *
 * Student-facing form to configure and generate a practice set from uploaded
 * course material. On submit, POSTs to `/api/v1/student/practice-sets` and
 * navigates to the session page.
 *
 * Route: /student/practice/new
 */

import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import { coursesApi, topicsApi } from '../../lib/api'
import { useCreatePracticeSet } from '../../hooks/usePractice'
import type { Difficulty, QuestionType } from '../../types/api'

// ── Constants ─────────────────────────────────────────────────────

const SUPPORTED_TYPES: { value: QuestionType; label: string }[] = [
  { value: 'mcq', label: 'Multiple Choice (MCQ)' },
  { value: 'true_false', label: 'True / False' },
]

const DIFFICULTY_OPTIONS: { value: Difficulty; label: string }[] = [
  { value: 'easy', label: 'Easy' },
  { value: 'medium', label: 'Medium' },
  { value: 'hard', label: 'Hard' },
]

// ── Page ──────────────────────────────────────────────────────────

export default function PracticeCreatePage() {
  const navigate = useNavigate()
  const createMutation = useCreatePracticeSet()

  // ── Form state ────────────────────────────────────────────────
  const [courseId, setCourseId] = useState('')
  const [selectedTopicIds, setSelectedTopicIds] = useState<string[]>([])
  const [selectedTypes, setSelectedTypes] = useState<QuestionType[]>(['mcq'])
  const [count, setCount] = useState(5)
  const [difficulty, setDifficulty] = useState<Difficulty | ''>('')
  const [title, setTitle] = useState('')

  // ── Data fetching ─────────────────────────────────────────────
  const { data: courses, isLoading: coursesLoading } = useQuery({
    queryKey: ['courses'],
    queryFn: () => coursesApi.list(),
  })

  const { data: topics, isLoading: topicsLoading } = useQuery({
    queryKey: ['topics', courseId],
    queryFn: () => topicsApi.listByCourse(courseId),
    enabled: Boolean(courseId),
    select: (data) => data.topics,
  })

  // ── Handlers ──────────────────────────────────────────────────

  function handleCourseChange(id: string) {
    setCourseId(id)
    setSelectedTopicIds([])   // reset topics when course changes
  }

  function toggleType(type: QuestionType) {
    setSelectedTypes((prev) =>
      prev.includes(type)
        ? prev.filter((t) => t !== type)
        : [...prev, type],
    )
  }

  function toggleTopic(id: string) {
    setSelectedTopicIds((prev) =>
      prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id],
    )
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!courseId || selectedTypes.length === 0) return

    try {
      const result = await createMutation.mutateAsync({
        course_id: courseId,
        topic_ids: selectedTopicIds.length > 0 ? selectedTopicIds : undefined,
        question_types: selectedTypes,
        count,
        difficulty: difficulty || undefined,
        title: title.trim() || undefined,
      })
      navigate(`/student/practice/${result.id}`)
    } catch {
      // error displayed below
    }
  }

  // ── Render ────────────────────────────────────────────────────
  return (
    <div style={styles.container}>
      <h1 style={styles.heading}>Create Practice Set</h1>
      <p style={styles.subtitle}>
        Generate practice questions from your course material. Only uploaded
        and processed PDF content is used — no outside knowledge.
      </p>

      <form onSubmit={handleSubmit} style={styles.form}>
        {/* Course */}
        <section style={styles.section}>
          <label style={styles.label} htmlFor="course-select">
            Course <span style={styles.required}>*</span>
          </label>
          {coursesLoading ? (
            <p style={styles.hint}>Loading courses…</p>
          ) : (
            <select
              id="course-select"
              value={courseId}
              onChange={(e) => handleCourseChange(e.target.value)}
              style={styles.select}
              required
            >
              <option value="">— Select a course —</option>
              {courses?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          )}
        </section>

        {/* Topics */}
        {courseId && (
          <section style={styles.section}>
            <div style={styles.label}>
              Topics{' '}
              <span style={styles.hint}>
                (optional — leave unchecked to use all course material)
              </span>
            </div>
            {topicsLoading ? (
              <p style={styles.hint}>Loading topics…</p>
            ) : topics && topics.length > 0 ? (
              <div style={styles.checkGrid}>
                {topics.map((t) => (
                  <label key={t.id} style={styles.checkLabel}>
                    <input
                      type="checkbox"
                      checked={selectedTopicIds.includes(t.id)}
                      onChange={() => toggleTopic(t.id)}
                    />
                    {' '}{t.name}
                  </label>
                ))}
              </div>
            ) : (
              <p style={styles.hint}>No topics extracted yet for this course.</p>
            )}
          </section>
        )}

        {/* Question types */}
        <section style={styles.section}>
          <div style={styles.label}>
            Question Types <span style={styles.required}>*</span>
          </div>
          <div style={styles.checkGrid}>
            {SUPPORTED_TYPES.map(({ value, label }) => (
              <label key={value} style={styles.checkLabel}>
                <input
                  type="checkbox"
                  checked={selectedTypes.includes(value)}
                  onChange={() => toggleType(value)}
                />
                {' '}{label}
              </label>
            ))}
          </div>
          {selectedTypes.length === 0 && (
            <p style={styles.error}>Select at least one question type.</p>
          )}
        </section>

        {/* Count */}
        <section style={styles.section}>
          <label style={styles.label} htmlFor="count-input">
            Number of questions
          </label>
          <input
            id="count-input"
            type="number"
            min={1}
            max={30}
            value={count}
            onChange={(e) => setCount(Number(e.target.value))}
            style={{ ...styles.select, width: 100 }}
          />
          <span style={{ ...styles.hint, marginLeft: 8 }}>max 30</span>
        </section>

        {/* Difficulty */}
        <section style={styles.section}>
          <label style={styles.label} htmlFor="difficulty-select">
            Difficulty
          </label>
          <select
            id="difficulty-select"
            value={difficulty}
            onChange={(e) => setDifficulty(e.target.value as Difficulty | '')}
            style={styles.select}
          >
            <option value="">Any (defaults to Medium)</option>
            {DIFFICULTY_OPTIONS.map(({ value, label }) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </section>

        {/* Title (optional) */}
        <section style={styles.section}>
          <label style={styles.label} htmlFor="title-input">
            Title <span style={styles.hint}>(optional)</span>
          </label>
          <input
            id="title-input"
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Week 3 revision"
            maxLength={255}
            style={styles.select}
          />
        </section>

        {/* Error */}
        {createMutation.isError && (
          <p style={styles.error}>
            Failed to generate practice set.{' '}
            {createMutation.error?.message ?? 'Please try again.'}
          </p>
        )}

        {/* Actions */}
        <div style={styles.actions}>
          <button
            type="submit"
            style={styles.primaryBtn}
            disabled={
              !courseId ||
              selectedTypes.length === 0 ||
              createMutation.isPending
            }
          >
            {createMutation.isPending ? 'Generating…' : '▶ Generate Practice Set'}
          </button>
          <Link to="/student" style={styles.cancelLink}>
            Cancel
          </Link>
        </div>
      </form>
    </div>
  )
}

// ── Styles ────────────────────────────────────────────────────────

const styles: Record<string, React.CSSProperties> = {
  container: {
    maxWidth: 680,
    margin: '40px auto',
    padding: '0 16px',
    fontFamily: 'system-ui, sans-serif',
  },
  heading: {
    fontSize: '1.6rem',
    marginBottom: 4,
  },
  subtitle: {
    color: '#555',
    marginBottom: 32,
    lineHeight: 1.5,
  },
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: 0,
  },
  section: {
    marginBottom: 24,
  },
  label: {
    display: 'block',
    fontWeight: 600,
    marginBottom: 6,
    fontSize: '0.95rem',
  },
  required: {
    color: '#c00',
  },
  hint: {
    color: '#888',
    fontSize: '0.85rem',
    fontWeight: 400,
  },
  select: {
    padding: '6px 10px',
    fontSize: '0.95rem',
    border: '1px solid #ccc',
    borderRadius: 4,
    minWidth: 260,
  },
  checkGrid: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
  },
  checkLabel: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    fontSize: '0.95rem',
    cursor: 'pointer',
  },
  error: {
    color: '#c00',
    fontSize: '0.88rem',
    marginTop: 4,
  },
  actions: {
    display: 'flex',
    alignItems: 'center',
    gap: 20,
    marginTop: 8,
  },
  primaryBtn: {
    padding: '10px 24px',
    background: '#1a73e8',
    color: '#fff',
    border: 'none',
    borderRadius: 4,
    fontSize: '0.98rem',
    cursor: 'pointer',
    fontWeight: 600,
  },
  cancelLink: {
    color: '#555',
    fontSize: '0.95rem',
    textDecoration: 'none',
  },
}

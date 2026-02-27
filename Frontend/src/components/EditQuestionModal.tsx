/**
 * EditQuestionModal
 *
 * A modal-style dialog for editing question body, difficulty, bloom level,
 * and (for MCQ) individual options.
 */

import React, { useEffect, useState } from 'react'
import type {
  QuestionDetail,
  Difficulty,
  BloomLevel,
  MCQOptionUpdate,
  QuestionUpdateRequest,
} from '../types/api'
import { useUpdateQuestion } from '../hooks/useQuestions'

interface Props {
  courseId: string
  question: QuestionDetail
  onClose: () => void
}

const DIFFICULTIES: Difficulty[] = ['easy', 'medium', 'hard']
const BLOOM_LEVELS: BloomLevel[] = ['remember', 'understand', 'apply', 'analyze', 'evaluate', 'create']

export default function EditQuestionModal({ courseId, question, onClose }: Props) {
  const updateMutation = useUpdateQuestion(courseId, question.id)

  // ── Local form state ───────────────────────────────────────────

  const [body, setBody] = useState(question.body)
  const [correctAnswer, setCorrectAnswer] = useState(question.correct_answer ?? '')
  const [explanation, setExplanation] = useState(question.explanation ?? '')
  const [difficulty, setDifficulty] = useState<Difficulty>(question.difficulty)
  const [bloomLevel, setBloomLevel] = useState<BloomLevel | ''>(question.bloom_level ?? '')

  // MCQ options — track text + is_correct per option
  const [mcqOptions, setMcqOptions] = useState<
    { id: string; label: string; text: string; is_correct: boolean }[]
  >(question.mcq_options.map(o => ({ ...o })))

  // Keep local state in sync if question prop changes
  useEffect(() => {
    setBody(question.body)
    setCorrectAnswer(question.correct_answer ?? '')
    setExplanation(question.explanation ?? '')
    setDifficulty(question.difficulty)
    setBloomLevel(question.bloom_level ?? '')
    setMcqOptions(question.mcq_options.map(o => ({ ...o })))
  }, [question.id]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Handlers ──────────────────────────────────────────────────

  function setOptionText(index: number, text: string) {
    setMcqOptions(prev => prev.map((o, i) => i === index ? { ...o, text } : o))
  }

  function setOptionCorrect(index: number) {
    setMcqOptions(prev =>
      prev.map((o, i) => ({ ...o, is_correct: i === index }))
    )
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const payload: QuestionUpdateRequest = {}

    if (body.trim() !== question.body) payload.body = body.trim()
    if (explanation.trim() !== (question.explanation ?? '')) payload.explanation = explanation.trim() || undefined
    if (difficulty !== question.difficulty) payload.difficulty = difficulty
    if ((bloomLevel || null) !== question.bloom_level) payload.bloom_level = (bloomLevel as BloomLevel) || undefined

    if (question.type === 'mcq') {
      // Only send changed options
      const updates: MCQOptionUpdate[] = mcqOptions
        .filter((opt, i) => {
          const orig = question.mcq_options[i]
          return opt.text !== orig.text || opt.is_correct !== orig.is_correct
        })
        .map(opt => ({
          id: opt.id,
          text: opt.text,
          is_correct: opt.is_correct,
        }))
      if (updates.length > 0) payload.mcq_options = updates
    } else {
      // true_false / short_answer / essay
      const trimmedCA = correctAnswer.trim()
      if (trimmedCA !== (question.correct_answer ?? '')) payload.correct_answer = trimmedCA
    }

    if (Object.keys(payload).length === 0) {
      onClose()
      return
    }

    updateMutation.mutate(payload, {
      onSuccess: () => onClose(),
    })
  }

  // ── Render ────────────────────────────────────────────────────

  return (
    <div style={s.overlay} onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={s.modal} role="dialog" aria-modal="true" aria-label="Edit question">
        <div style={s.header}>
          <h2 style={s.title}>Edit Question</h2>
          <button style={s.close} onClick={onClose} aria-label="Close">✕</button>
        </div>

        <form onSubmit={handleSubmit} style={s.form}>
          {/* Question body */}
          <label style={s.label}>Question Text</label>
          <textarea
            style={s.textarea}
            value={body}
            onChange={e => setBody(e.target.value)}
            rows={4}
            required
          />

          {/* MCQ options */}
          {question.type === 'mcq' && (
            <div style={s.optionBlock}>
              <label style={s.label}>Options</label>
              {mcqOptions.map((opt, i) => (
                <div key={opt.id} style={s.optionRow}>
                  <span style={s.optionLabel}>{opt.label}</span>
                  <input
                    style={s.optionInput}
                    value={opt.text}
                    onChange={e => setOptionText(i, e.target.value)}
                    required
                  />
                  <label style={s.correctLabel}>
                    <input
                      type="radio"
                      name="correct_option"
                      checked={opt.is_correct}
                      onChange={() => setOptionCorrect(i)}
                    />
                    Correct
                  </label>
                </div>
              ))}
            </div>
          )}

          {/* Correct answer for non-MCQ */}
          {question.type !== 'mcq' && (
            <>
              <label style={s.label}>Correct Answer</label>
              <input
                style={s.input}
                value={correctAnswer}
                onChange={e => setCorrectAnswer(e.target.value)}
              />
            </>
          )}

          {/* Difficulty + Bloom row */}
          <div style={s.row}>
            <div style={s.col}>
              <label style={s.label}>Difficulty</label>
              <select
                style={s.select}
                value={difficulty}
                onChange={e => setDifficulty(e.target.value as Difficulty)}
              >
                {DIFFICULTIES.map(d => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
            </div>
            <div style={s.col}>
              <label style={s.label}>Bloom Level</label>
              <select
                style={s.select}
                value={bloomLevel}
                onChange={e => setBloomLevel(e.target.value as BloomLevel | '')}
              >
                <option value="">—</option>
                {BLOOM_LEVELS.map(b => (
                  <option key={b} value={b}>{b}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Explanation */}
          <label style={s.label}>Explanation (optional)</label>
          <textarea
            style={s.textarea}
            value={explanation}
            onChange={e => setExplanation(e.target.value)}
            rows={3}
            placeholder="Explain why this answer is correct…"
          />

          {/* Error */}
          {updateMutation.isError && (
            <p style={s.error}>
              Failed to save: {updateMutation.error?.message}
            </p>
          )}

          {/* Actions */}
          <div style={s.actions}>
            <button
              type="button"
              style={s.btnSecondary}
              onClick={onClose}
              disabled={updateMutation.isPending}
            >
              Cancel
            </button>
            <button
              type="submit"
              style={s.btnPrimary}
              disabled={updateMutation.isPending}
            >
              {updateMutation.isPending ? 'Saving…' : 'Save Changes'}
            </button>
          </div>
        </form>
      </div>
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
    maxWidth: 640,
    maxHeight: '90vh',
    overflow: 'auto',
    boxShadow: '0 12px 40px rgba(0,0,0,0.2)',
    display: 'flex',
    flexDirection: 'column',
  },
  header: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '18px 24px 12px',
    borderBottom: '1px solid #eee',
    position: 'sticky', top: 0, background: '#fff', zIndex: 1,
  },
  title: { margin: 0, fontSize: 18, fontWeight: 600, color: '#1a1a1a' },
  close: {
    background: 'transparent', border: 'none', fontSize: 18,
    cursor: 'pointer', color: '#666', padding: '2px 6px',
  },
  form: { padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 14 },
  label: { fontWeight: 600, fontSize: 13, color: '#444', marginBottom: 4, display: 'block' },
  textarea: {
    width: '100%', padding: '8px 10px', borderRadius: 6,
    border: '1px solid #d1d5db', fontSize: 14, lineHeight: 1.5,
    fontFamily: 'system-ui, sans-serif', resize: 'vertical',
    boxSizing: 'border-box',
  },
  input: {
    width: '100%', padding: '8px 10px', borderRadius: 6,
    border: '1px solid #d1d5db', fontSize: 14,
    boxSizing: 'border-box',
  },
  select: {
    width: '100%', padding: '8px 10px', borderRadius: 6,
    border: '1px solid #d1d5db', fontSize: 14,
    background: '#fff', boxSizing: 'border-box',
  },
  row: { display: 'flex', gap: 16 },
  col: { flex: 1, display: 'flex', flexDirection: 'column' },
  optionBlock: { display: 'flex', flexDirection: 'column', gap: 8 },
  optionRow: { display: 'flex', alignItems: 'center', gap: 8 },
  optionLabel: {
    fontWeight: 700, fontSize: 13, color: '#5c6ac4',
    width: 20, flexShrink: 0,
  },
  optionInput: {
    flex: 1, padding: '6px 10px', borderRadius: 6,
    border: '1px solid #d1d5db', fontSize: 14,
  },
  correctLabel: {
    display: 'flex', alignItems: 'center', gap: 4,
    fontSize: 13, color: '#444', whiteSpace: 'nowrap',
  },
  actions: { display: 'flex', justifyContent: 'flex-end', gap: 12, marginTop: 4 },
  btnPrimary: {
    background: '#5c6ac4', color: '#fff',
    border: 'none', borderRadius: 6,
    padding: '9px 22px', fontSize: 14, cursor: 'pointer',
    fontWeight: 600,
  },
  btnSecondary: {
    background: '#f1f1f1', color: '#333',
    border: '1px solid #d1d5db', borderRadius: 6,
    padding: '9px 22px', fontSize: 14, cursor: 'pointer',
  },
  error: { color: '#c0392b', fontSize: 13, margin: 0 },
}

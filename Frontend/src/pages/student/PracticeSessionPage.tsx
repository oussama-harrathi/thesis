/**
 * PracticeSessionPage
 *
 * Displays a generated practice set with per-question answer reveal.
 * Loaded by ID from the URL param; the cache is pre-seeded by
 * useCreatePracticeSet so navigation from the create form is instant.
 *
 * Route: /student/practice/:questionSetId
 */

import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { usePracticeSet } from '../../hooks/usePractice'
import type {
  QuestionDetail,
  MCQOptionResponse,
  QuestionSourceResponse,
} from '../../types/api'

// ── Page ──────────────────────────────────────────────────────────

export default function PracticeSessionPage() {
  const { questionSetId } = useParams<{ questionSetId: string }>()
  const { data, isLoading, isError } = usePracticeSet(questionSetId ?? null)

  const [revealedAll, setRevealedAll] = useState(false)
  const [revealedIds, setRevealedIds] = useState<Set<string>>(new Set())

  function revealQuestion(id: string) {
    setRevealedIds((prev) => new Set([...prev, id]))
  }

  function handleRevealAll() {
    setRevealedAll(true)
    if (data) {
      setRevealedIds(new Set(data.questions.map((q) => q.id)))
    }
  }

  if (isLoading) {
    return (
      <div style={styles.container}>
        <p style={styles.hint}>Loading practice set…</p>
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div style={styles.container}>
        <p style={styles.error}>Practice set not found.</p>
        <Link to="/student/practice/new" style={styles.link}>
          ← Create a new practice set
        </Link>
      </div>
    )
  }

  const totalRevealed = revealedAll ? data.questions.length : revealedIds.size
  const allRevealed = totalRevealed === data.questions.length

  return (
    <div style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <div>
          <h1 style={styles.heading}>
            {data.title ?? 'Practice Session'}
          </h1>
          <p style={styles.subtitle}>
            {data.generated} question{data.generated !== 1 ? 's' : ''} generated
            {' · '}
            <span style={totalRevealed > 0 ? styles.revealedBadge : styles.hint}>
              {totalRevealed} / {data.questions.length} revealed
            </span>
          </p>
        </div>
        <div style={styles.headerActions}>
          {!allRevealed && (
            <button onClick={handleRevealAll} style={styles.revealAllBtn}>
              Reveal All Answers
            </button>
          )}
          <Link to="/student/practice/new" style={styles.newPracticeLink}>
            + New practice set
          </Link>
        </div>
      </div>

      {/* Empty state */}
      {data.questions.length === 0 && (
        <div style={styles.emptyBox}>
          <p>
            No questions were generated. This can happen when uploaded course
            documents have not been processed yet, or when the selected topics
            have no matching content.
          </p>
          <Link to="/student/practice/new" style={styles.link}>
            ← Try again with different settings
          </Link>
        </div>
      )}

      {/* Question list */}
      {data.questions.map((question, idx) => (
        <QuestionCard
          key={question.id}
          question={question}
          index={idx + 1}
          revealed={revealedIds.has(question.id)}
          onReveal={() => revealQuestion(question.id)}
        />
      ))}

      {/* Footer nav */}
      {data.questions.length > 0 && (
        <div style={styles.footer}>
          <Link to="/student/practice/new" style={styles.link}>
            ← Create another practice set
          </Link>
          <Link to="/student" style={styles.link}>
            Student Dashboard
          </Link>
        </div>
      )}
    </div>
  )
}

// ── QuestionCard ──────────────────────────────────────────────────

interface QuestionCardProps {
  question: QuestionDetail
  index: number
  revealed: boolean
  onReveal: () => void
}

function QuestionCard({ question, index, revealed, onReveal }: QuestionCardProps) {
  // Client-side selection tracking (local only, not submitted)
  const [selectedOption, setSelectedOption] = useState<string | null>(null)

  const typeBadgeColor: Record<string, string> = {
    mcq: '#1a73e8',
    true_false: '#0b8043',
    short_answer: '#e37400',
    essay: '#6b3fa0',
  }

  const difficultyColor: Record<string, string> = {
    easy: '#0b8043',
    medium: '#e37400',
    hard: '#c40000',
  }

  return (
    <div style={styles.card}>
      {/* Card header row */}
      <div style={styles.cardHeader}>
        <span style={styles.questionNum}>Q{index}</span>
        <span
          style={{
            ...styles.typeBadge,
            background: typeBadgeColor[question.type] ?? '#555',
          }}
        >
          {question.type.replace('_', '/')}
        </span>
        <span
          style={{
            ...styles.diffBadge,
            color: difficultyColor[question.difficulty] ?? '#555',
          }}
        >
          {question.difficulty}
        </span>
        {question.bloom_level && (
          <span style={styles.bloomBadge}>{question.bloom_level}</span>
        )}
      </div>

      {/* Body */}
      <p style={styles.body}>{question.body}</p>

      {/* MCQ options */}
      {question.type === 'mcq' && (
        <div style={styles.optionList}>
          {question.mcq_options.map((opt) => (
            <MCQOptionRow
              key={opt.id}
              option={opt}
              selected={selectedOption === opt.id}
              revealed={revealed}
              onSelect={() => !revealed && setSelectedOption(opt.id)}
            />
          ))}
        </div>
      )}

      {/* True/False options */}
      {question.type === 'true_false' && (
        <div style={styles.tfRow}>
          {['True', 'False'].map((val) => {
            const isSelected = selectedOption === val
            const isCorrect = revealed && question.correct_answer === val
            const isWrong = revealed && isSelected && question.correct_answer !== val
            return (
              <button
                key={val}
                onClick={() => !revealed && setSelectedOption(val)}
                disabled={revealed}
                style={{
                  ...styles.tfBtn,
                  ...(isCorrect ? styles.correctBtn : {}),
                  ...(isWrong ? styles.wrongBtn : {}),
                  ...(isSelected && !revealed ? styles.selectedBtn : {}),
                }}
              >
                {isCorrect ? `✓ ${val}` : isWrong ? `✗ ${val}` : val}
              </button>
            )
          })}
        </div>
      )}

      {/* Reveal / Answer section */}
      {!revealed ? (
        <button onClick={onReveal} style={styles.revealBtn}>
          Reveal Answer
        </button>
      ) : (
        <AnswerReveal question={question} />
      )}
    </div>
  )
}

// ── MCQOptionRow ──────────────────────────────────────────────────

interface MCQOptionRowProps {
  option: MCQOptionResponse
  selected: boolean
  revealed: boolean
  onSelect: () => void
}

function MCQOptionRow({ option, selected, revealed, onSelect }: MCQOptionRowProps) {
  const isCorrect = revealed && option.is_correct
  const isWrong = revealed && selected && !option.is_correct

  return (
    <div
      onClick={onSelect}
      style={{
        ...styles.optionRow,
        ...(selected && !revealed ? styles.optionSelected : {}),
        ...(isCorrect ? styles.optionCorrect : {}),
        ...(isWrong ? styles.optionWrong : {}),
        cursor: revealed ? 'default' : 'pointer',
      }}
    >
      <span style={styles.optionLabel}>{option.label}</span>
      <span>{option.text}</span>
      {isCorrect && <span style={styles.tick}>✓</span>}
      {isWrong && <span style={styles.cross}>✗</span>}
    </div>
  )
}

// ── AnswerReveal ──────────────────────────────────────────────────

function AnswerReveal({ question }: { question: QuestionDetail }) {
  return (
    <div style={styles.revealBox}>
      {/* Correct answer (for non-MCQ) */}
      {question.type !== 'mcq' && question.correct_answer && (
        <div style={styles.answerRow}>
          <span style={styles.answerLabel}>Correct answer: </span>
          <span style={styles.answerValue}>{question.correct_answer}</span>
        </div>
      )}

      {/* Explanation */}
      {question.explanation && (
        <div style={styles.explanationBlock}>
          <span style={styles.answerLabel}>Explanation</span>
          <p style={styles.explanationText}>{question.explanation}</p>
        </div>
      )}

      {/* Source snippets */}
      {question.sources.length > 0 && (
        <SourceSnippets sources={question.sources} />
      )}
    </div>
  )
}

// ── SourceSnippets ────────────────────────────────────────────────

function SourceSnippets({ sources }: { sources: QuestionSourceResponse[] }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div style={styles.sourcesBlock}>
      <button
        onClick={() => setExpanded((v) => !v)}
        style={styles.sourcesToggle}
      >
        {expanded ? '▾' : '▸'} Source snippets ({sources.length})
      </button>
      {expanded && (
        <div style={styles.snippetList}>
          {sources.map((s, i) => (
            <blockquote key={s.id} style={styles.snippet}>
              <span style={styles.snippetNum}>[{i + 1}]</span> {s.snippet}
            </blockquote>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Styles ────────────────────────────────────────────────────────

const styles: Record<string, React.CSSProperties> = {
  container: {
    maxWidth: 780,
    margin: '32px auto',
    padding: '0 16px',
    fontFamily: 'system-ui, sans-serif',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    flexWrap: 'wrap',
    gap: 12,
    marginBottom: 28,
  },
  heading: {
    fontSize: '1.55rem',
    margin: '0 0 4px',
  },
  subtitle: {
    color: '#555',
    margin: 0,
    fontSize: '0.93rem',
  },
  revealedBadge: {
    color: '#0b8043',
    fontWeight: 600,
  },
  hint: {
    color: '#888',
    fontSize: '0.88rem',
  },
  headerActions: {
    display: 'flex',
    gap: 12,
    alignItems: 'center',
  },
  revealAllBtn: {
    padding: '7px 16px',
    background: '#1a73e8',
    color: '#fff',
    border: 'none',
    borderRadius: 4,
    cursor: 'pointer',
    fontWeight: 600,
    fontSize: '0.9rem',
  },
  newPracticeLink: {
    color: '#1a73e8',
    textDecoration: 'none',
    fontSize: '0.9rem',
  },
  emptyBox: {
    background: '#fafafa',
    border: '1px solid #e0e0e0',
    borderRadius: 6,
    padding: '24px 20px',
    color: '#555',
    lineHeight: 1.6,
  },
  link: {
    color: '#1a73e8',
    textDecoration: 'none',
    fontSize: '0.93rem',
  },
  error: {
    color: '#c00',
  },
  card: {
    border: '1px solid #e0e0e0',
    borderRadius: 8,
    padding: '20px 22px',
    marginBottom: 20,
    background: '#fff',
    boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
  },
  cardHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 12,
    flexWrap: 'wrap',
  },
  questionNum: {
    fontWeight: 700,
    color: '#333',
    fontSize: '1rem',
    minWidth: 28,
  },
  typeBadge: {
    color: '#fff',
    padding: '2px 8px',
    borderRadius: 12,
    fontSize: '0.75rem',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.03em',
  },
  diffBadge: {
    fontSize: '0.8rem',
    fontWeight: 600,
    textTransform: 'capitalize',
  },
  bloomBadge: {
    background: '#f0f0f0',
    color: '#555',
    padding: '2px 7px',
    borderRadius: 10,
    fontSize: '0.75rem',
    textTransform: 'capitalize',
  },
  body: {
    fontSize: '1rem',
    lineHeight: 1.65,
    margin: '0 0 16px',
    color: '#222',
  },
  optionList: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    marginBottom: 14,
  },
  optionRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '8px 12px',
    borderRadius: 5,
    border: '1px solid #ddd',
    fontSize: '0.95rem',
    userSelect: 'none',
    transition: 'background 0.1s',
  },
  optionSelected: {
    background: '#e8f0fe',
    borderColor: '#1a73e8',
  },
  optionCorrect: {
    background: '#e6f4ea',
    borderColor: '#0b8043',
    color: '#0b8043',
    fontWeight: 600,
  },
  optionWrong: {
    background: '#fce8e6',
    borderColor: '#c40000',
    color: '#c40000',
  },
  optionLabel: {
    fontWeight: 700,
    minWidth: 20,
    color: '#555',
  },
  tick: {
    marginLeft: 'auto',
    fontWeight: 700,
    color: '#0b8043',
    fontSize: '1.1rem',
  },
  cross: {
    marginLeft: 'auto',
    fontWeight: 700,
    color: '#c40000',
    fontSize: '1.1rem',
  },
  tfRow: {
    display: 'flex',
    gap: 10,
    marginBottom: 14,
  },
  tfBtn: {
    padding: '8px 24px',
    border: '1px solid #ccc',
    borderRadius: 5,
    cursor: 'pointer',
    background: '#f9f9f9',
    fontSize: '0.95rem',
    fontWeight: 600,
    transition: 'background 0.1s',
  },
  selectedBtn: {
    background: '#e8f0fe',
    borderColor: '#1a73e8',
    color: '#1a73e8',
  },
  correctBtn: {
    background: '#e6f4ea',
    borderColor: '#0b8043',
    color: '#0b8043',
  },
  wrongBtn: {
    background: '#fce8e6',
    borderColor: '#c40000',
    color: '#c40000',
  },
  revealBtn: {
    marginTop: 4,
    padding: '7px 18px',
    background: '#f8f9fa',
    border: '1px solid #ccc',
    borderRadius: 4,
    cursor: 'pointer',
    fontSize: '0.9rem',
    color: '#333',
    fontWeight: 600,
  },
  revealBox: {
    marginTop: 12,
    paddingTop: 12,
    borderTop: '1px solid #e8e8e8',
  },
  answerRow: {
    marginBottom: 10,
    fontSize: '0.95rem',
  },
  answerLabel: {
    fontWeight: 700,
    color: '#333',
    marginRight: 4,
  },
  answerValue: {
    color: '#0b8043',
    fontWeight: 600,
  },
  explanationBlock: {
    marginBottom: 10,
  },
  explanationText: {
    margin: '4px 0 0',
    color: '#444',
    fontSize: '0.93rem',
    lineHeight: 1.6,
  },
  sourcesBlock: {
    marginTop: 8,
  },
  sourcesToggle: {
    background: 'none',
    border: 'none',
    color: '#1a73e8',
    cursor: 'pointer',
    fontSize: '0.87rem',
    padding: 0,
    fontWeight: 600,
  },
  snippetList: {
    marginTop: 8,
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
  },
  snippet: {
    margin: 0,
    padding: '8px 12px',
    background: '#f5f5f5',
    borderLeft: '3px solid #ccc',
    borderRadius: '0 4px 4px 0',
    fontSize: '0.82rem',
    color: '#555',
    lineHeight: 1.55,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  },
  snippetNum: {
    fontWeight: 700,
    color: '#888',
  },
  footer: {
    display: 'flex',
    gap: 24,
    marginTop: 12,
    paddingTop: 16,
    borderTop: '1px solid #eee',
  },
}

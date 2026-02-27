/**
 * GenerationPage  — /courses/:courseId/generation/:jobId
 *
 * Polls the background Celery job that generates questions from a blueprint.
 * Auto-refreshes every 2 seconds until the job completes or fails.
 */

import { Link, useParams } from 'react-router-dom'
import { useJob } from '../../hooks/useJobs'
import { useCourse } from '../../hooks/useCourses'

const STATUS_LABEL: Record<string, string> = {
  pending:   '⏳ Queued — waiting for a worker to pick it up…',
  running:   '⚙️ Generating questions…',
  completed: '✅ Generation complete!',
  failed:    '❌ Generation failed.',
}

const STATUS_COLOR: Record<string, string> = {
  pending:   '#d97706',
  running:   '#5c6ac4',
  completed: '#16a34a',
  failed:    '#dc2626',
}

export default function GenerationPage() {
  const { courseId, jobId } = useParams<{ courseId: string; jobId: string }>()
  const { data: course } = useCourse(courseId)
  const { data: job, isLoading, error } = useJob(jobId ?? null)

  const status = job?.status ?? 'pending'
  const progress = job?.progress ?? 0
  const isDone = status === 'completed' || status === 'failed'

  return (
    <div style={s.container}>
      <p>
        <Link to={`/courses/${courseId}`} style={s.back}>
          ← {course?.name ?? 'Course'}
        </Link>
      </p>
      <h1 style={s.heading}>Generating Questions</h1>

      {isLoading && <p style={s.muted}>Loading job status…</p>}
      {error && <p style={s.error}>Failed to load job: {error.message}</p>}

      {job && (
        <div style={s.card}>
          {/* Status label */}
          <p style={{ ...s.statusText, color: STATUS_COLOR[status] }}>
            {STATUS_LABEL[status] ?? status}
          </p>

          {/* Progress bar */}
          <div style={s.barTrack}>
            <div
              style={{
                ...s.barFill,
                width: `${progress}%`,
                background: STATUS_COLOR[status],
                transition: 'width 0.4s ease',
              }}
            />
          </div>
          <p style={s.progressText}>{progress}%</p>

          {/* Message from worker */}
          {job.message && (
            <p style={s.message}>{job.message}</p>
          )}

          {/* Error detail */}
          {status === 'failed' && job.error && (
            <p style={s.error}>Error: {job.error}</p>
          )}

          {/* Pulsing indicator while running */}
          {!isDone && (
            <p style={s.muted}>Auto-refreshing every 2 seconds…</p>
          )}

          {/* CTA when done */}
          {status === 'completed' && (
            <div style={s.ctaBox}>
              <p style={{ margin: '0 0 12px', fontWeight: 600 }}>
                Questions are ready for review!
              </p>
              <Link
                to={`/courses/${courseId}/questions`}
                style={s.btnReview}
              >
                📋 Go to Question Review →
              </Link>
            </div>
          )}

          {status === 'failed' && (
            <div style={{ marginTop: 20 }}>
              <Link
                to={`/courses/${courseId}/blueprints/new`}
                style={s.btnRetry}
              >
                ← Try Again
              </Link>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  container: { maxWidth: 600, margin: '40px auto', padding: '0 16px', fontFamily: 'system-ui, sans-serif' },
  back: { color: '#5c6ac4', textDecoration: 'none' },
  heading: { margin: '8px 0 20px' },
  card: { background: '#fff', border: '1px solid #e2e4f0', borderRadius: 12, padding: '28px 32px', boxShadow: '0 2px 8px rgba(0,0,0,0.04)' },
  statusText: { fontWeight: 700, fontSize: '1.05rem', margin: '0 0 16px' },
  barTrack: { height: 14, background: '#f0f0f0', borderRadius: 99, overflow: 'hidden', margin: '0 0 8px' },
  barFill: { height: '100%', borderRadius: 99 },
  progressText: { margin: '0 0 12px', fontSize: '0.9rem', fontWeight: 600, color: '#555' },
  message: { color: '#444', fontSize: '0.9rem', margin: '8px 0' },
  muted: { color: '#999', fontSize: '0.85rem' },
  error: { color: '#dc2626', fontWeight: 500 },
  ctaBox: { marginTop: 24, padding: '16px 20px', background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8 },
  btnReview: { display: 'inline-block', padding: '10px 22px', background: '#5c6ac4', color: '#fff', textDecoration: 'none', borderRadius: 6, fontWeight: 700 },
  btnRetry: { display: 'inline-block', padding: '10px 22px', background: '#f0f0f0', color: '#333', textDecoration: 'none', borderRadius: 6, fontWeight: 600 },
}

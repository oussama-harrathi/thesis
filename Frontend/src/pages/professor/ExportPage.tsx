/**
 * Export Page — /exams/:examId/export
 *
 * Professor workflow:
 *   1. Click "Export Exam" to trigger server-side LaTeX / PDF generation.
 *   2. The export list refreshes automatically (polls while status is pending).
 *   3. Each completed export shows a Download button.
 *   4. Failed exports show the error message.
 *
 * Both the exam document and its answer key are generated in one shot.
 */

import React from 'react'
import { Link, useParams } from 'react-router-dom'
import { useExamExports, useTriggerExport } from '../../hooks/useExports'
import { exportsApi } from '../../lib/api'
import type { ExportRecord, ExportType } from '../../types/api'

// ── Label helpers ─────────────────────────────────────────────────────────────

const TYPE_LABEL: Record<ExportType, string> = {
  exam_pdf: 'Exam PDF',
  answer_key_pdf: 'Answer Key PDF',
  exam_tex: 'Exam LaTeX',
  answer_key_tex: 'Answer Key LaTeX',
}

const STATUS_COLOR: Record<string, string> = {
  pending: '#d97706',
  completed: '#16a34a',
  failed: '#dc2626',
}

// ── Sub-components ────────────────────────────────────────────────────────────

function ExportRow({ record }: { record: ExportRecord }) {
  const label = TYPE_LABEL[record.export_type] ?? record.export_type
  const color = STATUS_COLOR[record.status] ?? '#6b7280'
  const downloadUrl = record.status === 'completed' && record.filename
    ? exportsApi.downloadUrl(record.id)
    : null

  return (
    <div style={s.row}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={s.typeLabel}>{label}</span>
        <span style={{ ...s.badge, background: color }}>{record.status}</span>
      </div>

      {record.filename && (
        <span style={s.filename}>{record.filename}</span>
      )}

      {record.error_message && (
        <p style={s.errorMsg}>{record.error_message}</p>
      )}

      <div style={{ marginTop: 8, display: 'flex', gap: 10, alignItems: 'center' }}>
        {downloadUrl ? (
          <a
            href={downloadUrl}
            download={record.filename ?? undefined}
            style={s.downloadBtn}
          >
            ⬇ Download
          </a>
        ) : (
          record.status !== 'completed' && (
            <span style={{ fontSize: 13, color: '#9ca3af' }}>
              {record.status === 'pending' ? 'Generating…' : 'Not available'}
            </span>
          )
        )}

        <span style={s.timestamp}>
          {new Date(record.created_at).toLocaleString()}
        </span>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ExportPage() {
  const { examId } = useParams<{ examId: string }>()

  const { data: exports = [], isLoading, error } = useExamExports(examId)
  const trigger = useTriggerExport(examId)

  const hasPending = exports.some((e) => e.status === 'pending')

  const handleTrigger = () => {
    trigger.mutate()
  }

  return (
    <div style={s.page}>
      <Link to=".." relative="path" style={s.back}>
        ← Back to Exam Builder
      </Link>

      <h2 style={s.title}>📤 Export Exam</h2>
      <p style={s.subtitle}>
        Generate LaTeX source and (if possible) compiled PDFs for this exam.
        Both the student exam and the answer key are produced together.
      </p>

      {/* Trigger button */}
      <button
        onClick={handleTrigger}
        disabled={trigger.isPending || hasPending || !examId}
        style={{
          ...s.btn,
          opacity: trigger.isPending || hasPending || !examId ? 0.6 : 1,
        }}
      >
        {trigger.isPending || hasPending ? 'Generating…' : '⚡ Generate Export'}
      </button>

      {trigger.isError && (
        <p style={s.errorMsg}>
          Error triggering export:{' '}
          {trigger.error instanceof Error ? trigger.error.message : 'Unknown error.'}
        </p>
      )}

      {/* Export list */}
      <h3 style={{ marginTop: 32, marginBottom: 12, fontSize: 16, fontWeight: 700 }}>
        Export History
        {hasPending && (
          <span style={{ marginLeft: 10, fontSize: 13, color: '#d97706', fontWeight: 400 }}>
            (refreshing…)
          </span>
        )}
      </h3>

      {isLoading && <p style={{ color: '#9ca3af' }}>Loading…</p>}

      {error && (
        <p style={s.errorMsg}>
          Could not load exports:{' '}
          {error instanceof Error ? error.message : 'Unknown error.'}
        </p>
      )}

      {!isLoading && exports.length === 0 && (
        <p style={{ color: '#9ca3af', fontSize: 14 }}>
          No exports yet. Click "Generate Export" to create the first one.
        </p>
      )}

      <div style={s.list}>
        {exports.map((record) => (
          <ExportRow key={record.id} record={record} />
        ))}
      </div>
    </div>
  )
}

// ── Styles ───────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page: {
    maxWidth: 760,
    margin: '0 auto',
    padding: '32px 24px',
    fontFamily: 'system-ui, sans-serif',
    color: '#111827',
  },
  back: {
    color: '#4f46e5',
    textDecoration: 'none',
    fontSize: 14,
  },
  title: {
    marginTop: 16,
    marginBottom: 4,
    fontSize: 24,
    fontWeight: 800,
    letterSpacing: -0.5,
  },
  subtitle: {
    marginTop: 0,
    marginBottom: 24,
    fontSize: 14,
    color: '#6b7280',
    lineHeight: 1.6,
  },
  btn: {
    background: '#4f46e5',
    color: '#fff',
    border: 'none',
    borderRadius: 8,
    padding: '10px 20px',
    fontSize: 14,
    fontWeight: 600,
    cursor: 'pointer',
  },
  list: {
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
    marginTop: 8,
  },
  row: {
    border: '1px solid #e5e7eb',
    borderRadius: 10,
    padding: '14px 18px',
    background: '#fff',
    boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
  },
  typeLabel: {
    fontWeight: 700,
    fontSize: 15,
  },
  badge: {
    color: '#fff',
    fontSize: 11,
    fontWeight: 700,
    borderRadius: 20,
    padding: '2px 9px',
    textTransform: 'uppercase' as const,
    letterSpacing: 0.5,
  },
  filename: {
    display: 'block',
    fontSize: 12,
    color: '#6b7280',
    marginTop: 4,
    fontFamily: 'monospace',
  },
  errorMsg: {
    color: '#b91c1c',
    fontSize: 13,
    marginTop: 6,
    marginBottom: 0,
  },
  downloadBtn: {
    display: 'inline-block',
    background: '#16a34a',
    color: '#fff',
    borderRadius: 6,
    padding: '5px 14px',
    fontSize: 13,
    fontWeight: 600,
    textDecoration: 'none',
  },
  timestamp: {
    fontSize: 12,
    color: '#9ca3af',
  },
}

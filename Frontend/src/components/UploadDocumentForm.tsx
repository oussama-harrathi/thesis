/**
 * UploadDocumentForm — PDF upload widget for a course (Phase 3 / upload).
 *
 * Renders a simple file-picker form. On submit it calls the upload mutation
 * which POSTs multipart/form-data to /api/v1/courses/{courseId}/documents.
 * Shows inline success / error feedback.
 *
 * NOTE: No processing progress bar yet — that comes in Phase 4.
 */

import { useRef, useState } from 'react'
import { useUploadDocument } from '../hooks/useDocuments'

interface Props {
  courseId: string
}

export default function UploadDocumentForm({ courseId }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  const upload = useUploadDocument(courseId)

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0] ?? null
    setSelectedFile(file)
    setSuccess(null)
    setFormError(null)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!selectedFile) return

    setSuccess(null)
    setFormError(null)

    try {
      const result = await upload.mutateAsync(selectedFile)
      setSuccess(
        `"${result.document.original_filename}" uploaded. Job created (id: ${result.job_id}).`
      )
      setSelectedFile(null)
      if (inputRef.current) inputRef.current.value = ''
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : 'Upload failed.')
    }
  }

  return (
    <form onSubmit={handleSubmit} style={s.form}>
      <div style={s.row}>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,application/pdf"
          onChange={handleFileChange}
          style={s.fileInput}
          disabled={upload.isPending}
        />
        <button
          type="submit"
          style={{
            ...s.btn,
            opacity: !selectedFile || upload.isPending ? 0.5 : 1,
            cursor: !selectedFile || upload.isPending ? 'not-allowed' : 'pointer',
          }}
          disabled={!selectedFile || upload.isPending}
        >
          {upload.isPending ? 'Uploading…' : 'Upload PDF'}
        </button>
      </div>

      {selectedFile && !upload.isPending && !success && (
        <p style={s.fileInfo}>
          Selected: <strong>{selectedFile.name}</strong> ({(selectedFile.size / 1024).toFixed(1)} KB)
        </p>
      )}

      {success && <p style={s.success}>✓ {success}</p>}
      {formError && <p style={s.error}>{formError}</p>}

      <p style={s.hint}>PDF files only · max {import.meta.env.VITE_MAX_UPLOAD_MB ?? 50} MB</p>
    </form>
  )
}

const s: Record<string, React.CSSProperties> = {
  form: {
    background: '#f8f9ff', border: '1px solid #dde', borderRadius: 10,
    padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 8,
  },
  row: { display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' },
  fileInput: { flex: 1, fontSize: '0.9rem' },
  btn: {
    padding: '8px 18px', borderRadius: 8, border: 'none',
    background: '#5c6ac4', color: '#fff', fontWeight: 600, fontSize: '0.9rem',
  },
  fileInfo: { margin: 0, fontSize: '0.85rem', color: '#555' },
  success: { margin: 0, color: '#27ae60', fontSize: '0.88rem' },
  error: { margin: 0, color: '#c0392b', background: '#fdf0ee', padding: '6px 10px', borderRadius: 6, fontSize: '0.88rem' },
  hint: { margin: 0, fontSize: '0.78rem', color: '#aaa' },
}

import { useCallback, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { UploadCloud, FileText, X, Loader2 } from 'lucide-react'
import api from '../api/client.js'

function FileDropZone({ label, accept, multiple, files, onFiles, onRemove }) {
  const inputRef = useRef()
  const [dragging, setDragging] = useState(false)

  const handleDrop = useCallback((e) => {
    e.preventDefault()
    setDragging(false)
    const dropped = Array.from(e.dataTransfer.files)
    onFiles(multiple ? dropped : [dropped[0]])
  }, [multiple, onFiles])

  return (
    <div>
      <label className="block text-xs text-slate-400 mb-1.5">{label}</label>
      <div
        onClick={() => inputRef.current.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className="rounded-xl border-2 border-dashed p-6 text-center cursor-pointer transition-colors"
        style={{
          borderColor: dragging ? '#6366f1' : '#2a2d3e',
          background: dragging ? 'rgba(99,102,241,0.06)' : '#0f1117',
        }}
      >
        <UploadCloud size={24} className="mx-auto mb-2 text-slate-500" />
        <p className="text-sm text-slate-400">
          Drop {multiple ? 'files' : 'file'} here or <span className="text-blue-400">browse</span>
        </p>
        <p className="text-xs text-slate-600 mt-1">{accept}</p>
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          multiple={multiple}
          className="hidden"
          onChange={(e) => onFiles(Array.from(e.target.files))}
        />
      </div>

      {files.length > 0 && (
        <ul className="mt-2 space-y-1">
          {files.map((f, i) => (
            <li key={i} className="flex items-center gap-2 text-xs text-slate-400">
              <FileText size={12} className="text-slate-500" />
              <span className="flex-1 truncate">{f.name}</span>
              <button type="button" onClick={() => onRemove(i)} className="text-slate-600 hover:text-red-400">
                <X size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function NewSubmission() {
  const navigate = useNavigate()
  const [submissionFiles, setSubmissionFiles] = useState([])
  const [docFiles, setDocFiles] = useState([])
  const [submitting, setSubmitting] = useState(false)
  const [pollStatus, setPollStatus] = useState('')
  const [err, setErr] = useState('')

  async function handleSubmit(e) {
    e.preventDefault()
    if (submissionFiles.length === 0) { setErr('Submission JSON is required.'); return }
    setErr('')
    setSubmitting(true)
    setPollStatus('Uploading…')

    const form = new FormData()
    form.append('submission_file', submissionFiles[0])
    docFiles.forEach((f) => form.append('documents', f))

    let submissionId
    try {
      const r = await api.post('/submissions', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      submissionId = r.data.submission_id
    } catch {
      setErr('Upload failed. Check that the submission file is valid JSON.')
      setSubmitting(false)
      setPollStatus('')
      return
    }

    setPollStatus('Pipeline running…')
    const interval = setInterval(async () => {
      try {
        const r = await api.get(`/submissions/${submissionId}/status`)
        const status = r.data.status
        if (status === 'complete') {
          clearInterval(interval)
          navigate(`/submissions/${submissionId}`)
        } else if (status === 'error') {
          clearInterval(interval)
          setErr('Pipeline failed. Check server logs for details.')
          setSubmitting(false)
          setPollStatus('')
        }
      } catch {
        clearInterval(interval)
        setErr('Lost connection while polling status.')
        setSubmitting(false)
        setPollStatus('')
      }
    }, 2000)
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <h1 className="text-xl font-semibold text-white">New Submission</h1>

      <form onSubmit={handleSubmit} className="space-y-6">
        <div className="rounded-xl p-6 space-y-5" style={{ background: '#1a1d2e', border: '1px solid #2a2d3e' }}>
          <FileDropZone
            label="Submission JSON *"
            accept=".json"
            multiple={false}
            files={submissionFiles}
            onFiles={setSubmissionFiles}
            onRemove={() => setSubmissionFiles([])}
          />

          <FileDropZone
            label="Supporting Documents (optional)"
            accept=".pdf,.docx,.xlsx,.txt"
            multiple
            files={docFiles}
            onFiles={(f) => setDocFiles((prev) => [...prev, ...f])}
            onRemove={(i) => setDocFiles((prev) => prev.filter((_, idx) => idx !== i))}
          />
        </div>

        {err && (
          <div
            className="rounded-lg px-4 py-3 text-sm text-red-400"
            style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)' }}
          >
            {err}
          </div>
        )}

        {pollStatus && (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <Loader2 size={14} className="animate-spin" />
            {pollStatus}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full py-3 rounded-xl text-sm font-semibold bg-blue-600 hover:bg-blue-500 text-white transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
        >
          {submitting
            ? <><Loader2 size={16} className="animate-spin" /> Processing…</>
            : 'Submit for Assessment'
          }
        </button>
      </form>

      <div className="rounded-xl p-5" style={{ background: '#1a1d2e', border: '1px solid #2a2d3e' }}>
        <p className="text-sm font-medium text-slate-400 mb-3">Submission JSON format</p>
        <pre className="text-xs text-slate-500 overflow-x-auto leading-relaxed">{`{
  "submission_id": "optional-custom-id",
  "applicant_name": "Acme Financial Ltd",
  "jurisdiction": "Ireland",
  "declared_activities": ["payment processing"],
  "incorporation_date": "2020-01-15",
  "key_personnel": [{"name": "Jane Smith", "role": "CEO", "nationality": "IE"}],
  "document_refs": []
}`}</pre>
        <p className="text-xs text-slate-600 mt-3">
          Omit <code className="text-slate-500">submission_id</code> to auto-generate one.
          Upload supporting documents (PDF, DOCX, XLSX, TXT) using the drop zone above —
          they are saved alongside the submission and passed to the pipeline automatically.
        </p>
      </div>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { analyzeImages } from './lib/api'
import './App.css'

type BBox = { x_min: number; y_min: number; x_max: number; y_max: number }

type Group = { text: string; bbox: BBox }

type RuleResult = {
  rule: string
  status: 'MATCH' | 'MISMATCH' | 'MISSING' | 'REVIEW REQUIRED' | string
  expected?: string
  observed?: string | null
  match?: boolean
  [key: string]: unknown
}

type Validation = {
  category: string
  results: RuleResult[]
  overall_status: 'PASS' | 'FAIL' | 'REVIEW REQUIRED' | string
}

type ImageResult = {
  image_id: string
  filename: string
  error?: string
  category?: string
  token_count?: number
  groups?: Group[]
  validation?: Validation
}

type BatchResponse = {
  status: string
  image_count: number
  results: ImageResult[]
}

function statusClass(status: string | undefined): string {
  switch (status) {
    case 'PASS':
    case 'MATCH':
      return 'status status-pass'
    case 'FAIL':
    case 'MISMATCH':
      return 'status status-fail'
    case 'MISSING':
      return 'status status-missing'
    case 'REVIEW REQUIRED':
      return 'status status-review'
    default:
      return 'status'
  }
}

function ResultCard({ result, file }: { result: ImageResult; file?: File }) {
  const [imgSize, setImgSize] = useState<{ w: number; h: number } | null>(null)
  const [showGroups, setShowGroups] = useState(true)
  const [imageUrl, setImageUrl] = useState<string | undefined>(undefined)

  useEffect(() => {
    if (!file) {
      setImageUrl(undefined)
      return
    }
    const url = URL.createObjectURL(file)
    setImageUrl(url)
    return () => {
      URL.revokeObjectURL(url)
    }
  }, [file])

  const validation = result.validation
  const overall = validation?.overall_status
  const category = result.category ?? validation?.category ?? 'unknown'

  return (
    <div className="result-card">
      <header className="result-header">
        <div>
          <h3>{result.filename ?? result.image_id}</h3>
          <p className="muted">{result.image_id}</p>
        </div>
        <div className="badges">
          <span className="badge">Category: {category}</span>
          {overall && <span className={statusClass(overall)}>{overall}</span>}
        </div>
      </header>

      {result.error && <p className="error">Error: {result.error}</p>}

      {imageUrl && (
        <div
          className="image-wrap"
          style={imgSize ? { aspectRatio: `${imgSize.w} / ${imgSize.h}` } : undefined}
        >
          <img
            src={imageUrl}
            alt={result.filename}
            onLoad={(e) => {
              const el = e.currentTarget
              setImgSize({ w: el.naturalWidth, h: el.naturalHeight })
            }}
          />
          {imgSize && showGroups && result.groups && (
            <svg
              className="bbox-overlay"
              viewBox={`0 0 ${imgSize.w} ${imgSize.h}`}
              preserveAspectRatio="none"
            >
              {result.groups.map((g, i) => (
                <rect
                  key={i}
                  x={g.bbox.x_min}
                  y={g.bbox.y_min}
                  width={g.bbox.x_max - g.bbox.x_min}
                  height={g.bbox.y_max - g.bbox.y_min}
                  className="bbox"
                />
              ))}
            </svg>
          )}
        </div>
      )}

      <div className="controls">
        <label>
          <input
            type="checkbox"
            checked={showGroups}
            onChange={(e) => setShowGroups(e.target.checked)}
          />
          Show group bounding boxes ({result.groups?.length ?? 0})
        </label>
      </div>

      {validation && (
        <div className="rules">
          <h4>Validation rules ({validation.results.length})</h4>
          {validation.results.map((r) => (
            <details key={r.rule} className="rule">
              <summary>
                <span className="rule-name">{r.rule}</span>
                <span className={statusClass(r.status)}>{r.status}</span>
              </summary>
              <div className="rule-body">
                {r.expected !== undefined && (
                  <div>
                    <strong>Expected:</strong>
                    <pre>{r.expected}</pre>
                  </div>
                )}
                {r.observed !== undefined && r.observed !== null && (
                  <div>
                    <strong>Observed:</strong>
                    <pre>{r.observed}</pre>
                  </div>
                )}
                {typeof r.match === 'boolean' && (
                  <p>
                    <strong>Match:</strong> {r.match ? 'true' : 'false'}
                  </p>
                )}
              </div>
            </details>
          ))}
        </div>
      )}

      <details className="raw">
        <summary>Raw data</summary>
        <pre>{JSON.stringify(result, null, 2)}</pre>
      </details>
    </div>
  )
}

function App() {
  const [files, setFiles] = useState<File[]>([])
  const [result, setResult] = useState<BatchResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(event.target.files ?? [])
    setFiles(selected)
    setResult(null)
    setError(null)
  }

  const handleSubmit = async () => {
    if (files.length === 0) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const data = (await analyzeImages(files)) as BatchResponse
      setResult(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app">
      <h1>Alcohol Label Verification</h1>

      <div className="upload-bar">
        <label className="upload">
          <span>Select label images (JPG, JPEG, PNG)</span>
          <input
            type="file"
            accept="image/jpeg,image/jpg,image/png"
            multiple
            onChange={handleFileChange}
          />
        </label>

        <button
          type="button"
          className="primary"
          onClick={handleSubmit}
          disabled={files.length === 0 || loading}
        >
          {loading ? 'Analyzing...' : 'Analyze'}
        </button>
      </div>

      {files.length > 0 && (
        <p className="file-summary">{files.length} image(s) selected</p>
      )}

      {error && <p className="error">Error: {error}</p>}

      {result && (
        <div className="results">
          {result.results.map((r, i) => (
            <ResultCard key={r.image_id ?? i} result={r} file={files[i]} />
          ))}
        </div>
      )}
    </div>
  )
}

export default App

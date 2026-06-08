import { useState } from 'react'
import { analyzeImages } from './lib/api'
import './App.css'

function App() {
  const [files, setFiles] = useState<File[]>([])
  const [result, setResult] = useState<unknown>(null)
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
      const data = await analyzeImages(files)
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

      <label className="upload">
        <span>Select label images (JPG, JPEG, PNG)</span>
        <input
          type="file"
          accept="image/jpeg,image/jpg,image/png"
          multiple
          onChange={handleFileChange}
        />
      </label>

      {files.length > 0 && (
        <p className="file-summary">{files.length} image(s) selected</p>
      )}

      <button
        type="button"
        onClick={handleSubmit}
        disabled={files.length === 0 || loading}
      >
        {loading ? 'Analyzing...' : 'Analyze'}
      </button>

      {error && <p className="error">Error: {error}</p>}

      {result !== null && (
        <pre className="result">{JSON.stringify(result, null, 2)}</pre>
      )}
    </div>
  )
}

export default App

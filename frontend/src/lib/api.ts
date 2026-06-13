// VITE_API_BASE_URL must be the API base path with NO trailing /api
// segment appended by the caller. Convention:
//   - production (nginx reverse proxy):  "/api"
//   - dev (hitting the backend directly): "http://localhost:8000"
//
// `analyzeImages` appends `/analyze` to that base, so the final URL is
// `${VITE_API_BASE_URL}/analyze` in both cases.
const API_BASE_URL = (
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? ''
).replace(/\/+$/, '')

const ANALYZE_URL = `${API_BASE_URL}/analyze`

export async function analyzeImages(
  files: File[],
  metadata: { filename: string; expected_brand?: string }[],
): Promise<unknown> {
  const formData = new FormData()
  for (const file of files) {
    formData.append('images', file)
  }
  formData.append('metadata_json', JSON.stringify(metadata))

  const response = await fetch(ANALYZE_URL, {
    method: 'POST',
    body: formData,
  })

  if (!response.ok) {
    throw new Error(`Analyze request failed: ${response.status} ${response.statusText}`)
  }

  return response.json()
}

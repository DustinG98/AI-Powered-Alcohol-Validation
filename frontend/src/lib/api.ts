const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  'http://localhost:8000'

export async function analyzeImages(
  files: File[],
  metadata: { filename: string; expected_brand?: string }[],
): Promise<unknown> {
  const formData = new FormData()
  for (const file of files) {
    formData.append('images', file)
  }
  formData.append('metadata_json', JSON.stringify(metadata))

  const response = await fetch(`${API_BASE_URL}/api/analyze`, {
    method: 'POST',
    body: formData,
  })

  if (!response.ok) {
    throw new Error(`Analyze request failed: ${response.status} ${response.statusText}`)
  }

  return response.json()
}
import { useEffect, useRef, useState, useCallback } from 'react'
import { Upload, X, Loader2, ChevronDown, ImageIcon, AlertCircle } from 'lucide-react'
import { analyzeImages } from './lib/api'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { cn } from '@/lib/utils'
import './App.css'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type BBox = { x_min: number; y_min: number; x_max: number; y_max: number }

type Group = { text: string; bbox: BBox }

type RuleResult = {
  rule: string
  status: 'MATCH' | 'MISMATCH' | 'MISSING' | 'REVIEW REQUIRED' | string
  expected?: string
  observed?: string | null
  match?: boolean
  coverage?: number
  missing_tokens?: string[]
  detected_brand?: string | null
  detection_score?: number
  candidates?: { text: string; score: number }[]
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
  metadata?: Record<string, unknown>
  expected_brand_supplied?: boolean
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

type ImageEntry = {
  id: number
  file: File
  previewUrl: string
  expectedBrand: string
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type StatusKind = 'pass' | 'fail' | 'missing' | 'review' | 'neutral'

function statusKind(status: string | undefined): StatusKind {
  switch (status) {
    case 'PASS':
    case 'MATCH':
      return 'pass'
    case 'FAIL':
    case 'MISMATCH':
      return 'fail'
    case 'MISSING':
      return 'missing'
    case 'REVIEW REQUIRED':
      return 'review'
    default:
      return 'neutral'
  }
}

const statusBadgeClass = (kind: StatusKind) => {
  switch (kind) {
    case 'pass':
      return 'bg-emerald-600 text-white border-transparent hover:bg-emerald-600'
    case 'fail':
      return 'bg-red-600 text-white border-transparent hover:bg-red-600'
    case 'missing':
      return 'bg-zinc-500 text-white border-transparent hover:bg-zinc-500'
    case 'review':
      return 'bg-amber-500 text-zinc-900 border-transparent hover:bg-amber-500'
    default:
      return ''
  }
}

// ---------------------------------------------------------------------------
// Image card — shown before analysis
// ---------------------------------------------------------------------------

function ImageCard({
  entry,
  onRemove,
  onBrandChange,
}: {
  entry: ImageEntry
  onRemove: (id: number) => void
  onBrandChange: (id: number, brand: string) => void
}) {
  return (
    <Card size="sm" className="overflow-hidden">
      <div className="relative bg-muted">
        <img
          src={entry.previewUrl}
          alt={entry.file.name}
          className="block aspect-[4/3] w-full object-cover"
        />
        <Button
          type="button"
          size="icon-xs"
          variant="secondary"
          onClick={() => onRemove(entry.id)}
          aria-label="Remove image"
          className="absolute top-1.5 right-1.5 bg-black/55 text-white hover:bg-black/75"
        >
          <X />
        </Button>
      </div>
      <CardContent className="space-y-1.5 pt-3">
        <p
          className="truncate text-xs text-muted-foreground"
          title={entry.file.name}
        >
          {entry.file.name}
        </p>
        <Input
          type="text"
          placeholder="Expected brand (optional)"
          value={entry.expectedBrand}
          onChange={(e) => onBrandChange(entry.id, e.target.value)}
          className="h-8 text-xs"
        />
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Result card — shown after analysis. Collapsed by default: only image
// thumbnail, filename, and master pass/fail badge are visible.
// ---------------------------------------------------------------------------

function ResultCard({
  result,
  entry,
}: {
  result: ImageResult
  entry: ImageEntry | undefined
}) {
  const [showGroups, setShowGroups] = useState(false)
  const [imgSize, setImgSize] = useState<{ w: number; h: number } | null>(null)
  const [imageUrl, setImageUrl] = useState<string | undefined>(undefined)
  const [detailsOpen, setDetailsOpen] = useState(false)

  useEffect(() => {
    if (!entry) {
      setImageUrl(undefined)
      return
    }
    const url = URL.createObjectURL(entry.file)
    setImageUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [entry])

  const validation = result.validation
  const overall = validation?.overall_status
  const overallKind = statusKind(overall)
  const brandResult = validation?.results.find((r) => r.rule === 'brand_verification')
  const brandKind = statusKind(brandResult?.status as string | undefined)
  const ruleCount = validation?.results.length ?? 0

  return (
    <Card className="overflow-hidden">
      <Collapsible open={detailsOpen} onOpenChange={setDetailsOpen}>
        {/* Visible-by-default header: review chip on top, then
            image / filename / brand stacked vertically. */}
        <div className="flex flex-col gap-2 p-3">
          <div className="flex items-start justify-end gap-2">
            {overall && (
              <Badge className={cn(statusBadgeClass(overallKind))}>
                {overall}
              </Badge>
            )}
            <CollapsibleTrigger asChild>
              <Button
                type="button"
                size="icon-sm"
                variant="ghost"
                aria-label={detailsOpen ? 'Hide details' : 'Show details'}
              >
                <ChevronDown
                  className={cn(
                    'transition-transform',
                    detailsOpen && 'rotate-180',
                  )}
                />
              </Button>
            </CollapsibleTrigger>
          </div>

          {imageUrl ? (
            <img
              src={imageUrl}
              alt={result.filename}
              className="block h-auto w-full rounded-md object-cover"
            />
          ) : (
            <div className="bg-muted text-muted-foreground flex h-24 w-full items-center justify-center rounded-md">
              <ImageIcon className="size-6" />
            </div>
          )}

          <div className="w-full text-center">
            <p
              className="truncate text-xs font-medium"
              title={result.filename}
            >
              {result.filename}
            </p>
            {brandResult ? (
              <p className="text-muted-foreground text-xs">
                {brandResult.expected
                  ? brandResult.expected
                  : brandResult.detected_brand ?? '—'}
              </p>
            ) : (
              <p className="text-muted-foreground text-xs">—</p>
            )}
          </div>
        </div>

        <CollapsibleContent>
          {result.error && (
            <>
              <Separator />
              <CardContent className="pt-3">
                <p className="flex items-center gap-1.5 text-sm text-destructive">
                  <AlertCircle className="size-4" /> Error: {result.error}
                </p>
              </CardContent>
            </>
          )}

          {imageUrl && (
            <>
              <Separator />
              <div className="relative bg-muted">
                <img
                  src={imageUrl}
                  alt={result.filename}
                  className="block h-auto w-full"
                  onLoad={(e) => {
                    const el = e.currentTarget
                    setImgSize({ w: el.naturalWidth, h: el.naturalHeight })
                  }}
                />
                {imgSize && showGroups && result.groups && (
                  <svg
                    className="pointer-events-none absolute inset-0 block size-full"
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
                        className="fill-primary/10 stroke-primary"
                        strokeWidth={1.5}
                      />
                    ))}
                  </svg>
                )}
              </div>
              <div className="flex items-center gap-2 px-3 py-2">
                <Checkbox
                  id={`show-groups-${result.image_id}`}
                  checked={showGroups}
                  onCheckedChange={(checked) => setShowGroups(checked === true)}
                />
                <Label
                  htmlFor={`show-groups-${result.image_id}`}
                  className="text-xs"
                >
                  Show groups ({result.groups?.length ?? 0})
                </Label>
              </div>
            </>
          )}

          {brandResult && (
            <>
              <Separator />
              <div className="bg-accent/40 flex flex-wrap items-center gap-2 px-3 py-2 text-xs">
                <span className="font-semibold">Brand</span>
                <Badge className={cn(statusBadgeClass(brandKind))}>
                  {brandResult.status}
                </Badge>
                {brandResult.expected && (
                  <span className="text-muted-foreground">
                    Expected: {brandResult.expected}
                  </span>
                )}
                {brandResult.observed && (
                  <span className="text-muted-foreground">
                    Found: {brandResult.observed}
                  </span>
                )}
                {brandResult.missing_tokens &&
                  brandResult.missing_tokens.length > 0 && (
                    <span className="text-destructive">
                      Missing: {brandResult.missing_tokens.join(', ')}
                    </span>
                  )}
                {!brandResult.expected && brandResult.detected_brand && (
                  <span className="text-muted-foreground">
                    Detected: {brandResult.detected_brand}
                  </span>
                )}
              </div>
            </>
          )}

          {validation && (
            <>
              <Separator />
              <CardContent className="space-y-2 py-3">
                <p className="text-muted-foreground text-xs font-medium">
                  Validation ({ruleCount} rules)
                </p>
                {validation.results.map((r) => {
                  const kind = statusKind(r.status)
                  return (
                    <details
                      key={r.rule}
                      className="border-border bg-muted/40 overflow-hidden rounded-md border text-xs"
                    >
                      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-2.5 py-1.5 [&::-webkit-details-marker]:hidden">
                        <span className="font-mono">{r.rule}</span>
                        <Badge className={cn(statusBadgeClass(kind))}>
                          {r.status}
                        </Badge>
                      </summary>
                      <div className="space-y-1.5 border-t border-border bg-background p-2.5 text-xs">
                        {r.expected !== undefined && (
                          <div>
                            <strong>Expected:</strong>
                            <pre className="border-border bg-muted/30 mt-0.5 mb-1.5 max-w-full whitespace-pre-wrap break-words rounded border p-1.5 text-[0.7rem]">
                              {r.expected}
                            </pre>
                          </div>
                        )}
                        {r.observed !== undefined && r.observed !== null && (
                          <div>
                            <strong>Observed:</strong>
                            <pre className="border-border bg-muted/30 mt-0.5 mb-1.5 max-w-full whitespace-pre-wrap break-words rounded border p-1.5 text-[0.7rem]">
                              {r.observed}
                            </pre>
                          </div>
                        )}
                        {typeof r.coverage === 'number' && (
                          <p>
                            <strong>Coverage:</strong> {r.coverage}
                          </p>
                        )}
                        {r.missing_tokens && r.missing_tokens.length > 0 && (
                          <p>
                            <strong>Missing tokens:</strong>{' '}
                            {r.missing_tokens.join(', ')}
                          </p>
                        )}
                      </div>
                    </details>
                  )
                })}
              </CardContent>
            </>
          )}

          <Separator />
          <details className="text-xs">
            <summary className="text-muted-foreground flex cursor-pointer list-none items-center gap-1.5 bg-muted/40 px-3 py-2 [&::-webkit-details-marker]:hidden">
              <ChevronDown className="size-3.5" />
              Raw data
            </summary>
            <pre className="text-muted-foreground max-h-72 overflow-auto whitespace-pre-wrap break-words bg-background p-3 text-[0.7rem]">
              {JSON.stringify(result, null, 2)}
            </pre>
          </details>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Main App
// ---------------------------------------------------------------------------

let nextId = 1

function App() {
  const [entries, setEntries] = useState<ImageEntry[]>([])
  const [results, setResults] = useState<BatchResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const addFiles = useCallback((files: File[]) => {
    if (!files.length) return
    const newEntries: ImageEntry[] = files.map((file) => ({
      id: nextId++,
      file,
      previewUrl: URL.createObjectURL(file),
      expectedBrand: '',
    }))
    setEntries((prev) => {
      prev.forEach((e) => URL.revokeObjectURL(e.previewUrl))
      return newEntries
    })
    setResults(null)
    setError(null)
  }, [])

  const handleFileChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const files = Array.from(event.target.files ?? [])
      if (fileInputRef.current) fileInputRef.current.value = ''
      addFiles(files)
    },
    [addFiles],
  )

  const handleDrop = useCallback(
    (event: React.DragEvent<HTMLLabelElement>) => {
      event.preventDefault()
      setDragOver(false)
      const files = Array.from(event.dataTransfer.files ?? []).filter((f) =>
        f.type.startsWith('image/'),
      )
      addFiles(files)
    },
    [addFiles],
  )

  const handleRemove = useCallback((id: number) => {
    setEntries((prev) => {
      const entry = prev.find((e) => e.id === id)
      if (entry) URL.revokeObjectURL(entry.previewUrl)
      return prev.filter((e) => e.id !== id)
    })
  }, [])

  const handleBrandChange = useCallback((id: number, brand: string) => {
    setEntries((prev) =>
      prev.map((e) => (e.id === id ? { ...e, expectedBrand: brand } : e)),
    )
  }, [])

  const handleReset = useCallback(() => {
    setEntries((prev) => {
      prev.forEach((e) => URL.revokeObjectURL(e.previewUrl))
      return []
    })
    setResults(null)
    setError(null)
  }, [])

  const handleSubmit = async () => {
    if (entries.length === 0) return
    setLoading(true)
    setError(null)
    try {
      const metadata = entries.map((e) => ({
        filename: e.file.name,
        expected_brand: e.expectedBrand,
      }))
      const data = (await analyzeImages(
        entries.map((e) => e.file),
        metadata,
      )) as BatchResponse
      setResults(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  const showResults = results !== null

  return (
    <div className="mx-auto max-w-7xl px-5 py-6 pb-10">
      <header className="mb-8 text-center">
        <h1 className="font-heading text-2xl font-semibold tracking-tight">
          Alcohol Label Verification
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Upload label images, optionally set expected brand per image, then analyze.
        </p>
      </header>

      <div className="mb-6 flex items-center gap-4">
        <Label
          htmlFor="file-upload"
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          className={cn(
            'border-border bg-muted/40 hover:border-primary/60 hover:bg-accent/40 flex h-32 w-full cursor-pointer flex-col items-center justify-center gap-1.5 rounded-xl border-2 border-dashed px-5 py-6 text-center transition-colors',
            dragOver && 'border-primary bg-accent/60',
          )}
        >
          {entries.length === 0 ? (
            <Upload className="text-muted-foreground size-6" />
          ) : (
            <ImageIcon className="text-muted-foreground size-6" />
          )}
          <span className="text-foreground text-sm font-medium">
            {entries.length === 0
              ? 'Select images or drag & drop'
              : 'Replace images or drag & drop'}
          </span>
          <span className="text-muted-foreground text-xs">
            JPG, PNG — multiple files supported
          </span>
          <Input
            id="file-upload"
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/jpg,image/png"
            multiple
            onChange={handleFileChange}
            className="hidden"
          />
        </Label>

        {entries.length > 0 && !showResults && (
          <Button type="button" variant="outline" onClick={handleReset}>
            Clear all
          </Button>
        )}
      </div>

      {!showResults && entries.length > 0 && (
        <>
          <div className="mb-6 grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-4">
            {entries.map((entry) => (
              <ImageCard
                key={entry.id}
                entry={entry}
                onRemove={handleRemove}
                onBrandChange={handleBrandChange}
              />
            ))}
          </div>

          <div className="mb-6 flex justify-center">
            <Button
              type="button"
              size="lg"
              onClick={handleSubmit}
              disabled={loading}
            >
              {loading && <Loader2 className="animate-spin" />}
              {loading
                ? 'Analyzing...'
                : `Analyze ${entries.length} image${entries.length !== 1 ? 's' : ''}`}
            </Button>
          </div>
        </>
      )}

      {showResults && results && (
        <>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-heading text-xl font-semibold">Results</h2>
            <Button type="button" variant="outline" onClick={handleReset}>
              New upload
            </Button>
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {entries.map((entry) => {
              const result = results.results.find(
                (r) => r.filename === entry.file.name,
              )
              if (!result) return null
              return <ResultCard key={entry.id} result={result} entry={entry} />
            })}
          </div>
        </>
      )}

      {error && (
        <p className="text-destructive mt-2 flex items-center justify-center gap-1.5 text-center text-sm">
          <AlertCircle className="size-4" /> {error}
        </p>
      )}
    </div>
  )
}

export default App

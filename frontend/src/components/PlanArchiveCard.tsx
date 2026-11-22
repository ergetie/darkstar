import { useCallback, useEffect, useRef, useState } from 'react'
import { Archive, Download, Loader2, Trash2 } from 'lucide-react'
import Card from './Card'
import Modal from './ui/Modal'
import Select from './ui/Select'
import { Api, type PlanArchiveSummary } from '../lib/api'
import { downloadFile } from '../lib/download'
import { useToast } from '../lib/useToast'

type RangeValue = 'all' | '7d' | '24h'

const RANGE_OPTIONS: { label: string; value: RangeValue }[] = [
    { label: 'All', value: 'all' },
    { label: 'Last 7 days', value: '7d' },
    { label: 'Last 24 hours', value: '24h' },
]

const RANGE_DAYS: Record<RangeValue, number | null> = { all: null, '7d': 7, '24h': 1 }

const DOWNLOAD_URL = 'api/debug/plan-archive/download'

function formatBytes(bytes: number): string {
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(iso: string | null): string {
    return iso ? new Date(iso).toLocaleDateString() : '-'
}

export default function PlanArchiveCard() {
    const { toast } = useToast()
    const [summary, setSummary] = useState<PlanArchiveSummary | null>(null)
    const [loadError, setLoadError] = useState(false)
    const [range, setRange] = useState<RangeValue>('all')
    const [downloading, setDownloading] = useState(false)
    const downloadingRef = useRef(false)
    const [confirmOpen, setConfirmOpen] = useState(false)
    const [clearing, setClearing] = useState(false)

    const reload = useCallback(async () => {
        try {
            setSummary(await Api.planArchiveSummary())
            setLoadError(false)
        } catch {
            setLoadError(true)
        }
    }, [])

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch on mount
        void reload()
    }, [reload])

    const runDownload = async () => {
        if (downloadingRef.current) return
        downloadingRef.current = true
        setDownloading(true)
        try {
            const days = RANGE_DAYS[range]
            const url = days === null ? DOWNLOAD_URL : `${DOWNLOAD_URL}?days=${days}`
            await downloadFile(url, 'darkstar-plan-archive.zip')
        } catch (err) {
            toast({
                variant: 'error',
                message: 'Plan archive download failed',
                description: err instanceof Error ? err.message : 'Unknown error',
            })
        } finally {
            downloadingRef.current = false
            setDownloading(false)
        }
    }

    const confirmClear = async () => {
        setClearing(true)
        try {
            await Api.clearPlanArchive()
            setConfirmOpen(false)
            await reload()
        } catch (err) {
            toast({
                variant: 'error',
                message: 'Could not clear the plan archive',
                description: err instanceof Error ? err.message : 'Unknown error',
            })
        } finally {
            setClearing(false)
        }
    }

    const count = summary?.count ?? 0
    const empty = count === 0

    return (
        <Card className="p-5">
            <div className="flex items-center gap-2 text-sm text-muted mb-3">
                <Archive size={14} />
                Plan archive
            </div>
            <div className="text-[13px] text-muted/80 mb-3">
                A compressed record of every planner run (inputs, plan and errors). Download it to share for support.
            </div>

            {loadError && !summary && (
                <div className="banner banner-error mb-3">Could not load the plan archive summary.</div>
            )}
            {summary && !summary.enabled && (
                <div className="banner banner-warning mb-3">Archiving is disabled (debug.plan_archive_enabled).</div>
            )}

            {summary && (
                <div className="space-y-2 text-[12px] text-muted/90">
                    <div className="flex items-center justify-between">
                        <span>Runs archived</span>
                        <span className="tabular-nums" data-testid="plan-archive-count">
                            {count}
                        </span>
                    </div>
                    <div className="flex items-center justify-between">
                        <span>Size</span>
                        <span className="tabular-nums">{formatBytes(summary.total_bytes ?? 0)}</span>
                    </div>
                    <div className="flex items-center justify-between">
                        <span>Date range</span>
                        <span className="tabular-nums">
                            {empty ? '-' : `${formatDate(summary.oldest)} - ${formatDate(summary.newest)}`}
                        </span>
                    </div>
                    <div className="flex items-center justify-between">
                        <span>Kept for</span>
                        <span className="tabular-nums">{summary.retention_days} days</span>
                    </div>
                </div>
            )}

            <div className="mt-4 flex flex-wrap items-center gap-2">
                <Select
                    className="w-40"
                    value={range}
                    onChange={(v) => setRange(v as RangeValue)}
                    options={RANGE_OPTIONS}
                    disabled={downloading}
                />
                <button
                    type="button"
                    className="btn btn-primary btn-pill flex items-center gap-1.5 whitespace-nowrap"
                    onClick={runDownload}
                    disabled={empty || downloading}
                    aria-busy={downloading}
                >
                    {downloading ? <Loader2 size={12} className="animate-spin" /> : <Download size={12} />}
                    {downloading ? 'Preparing…' : 'Download'}
                </button>
                <button
                    type="button"
                    className="btn btn-danger btn-pill flex items-center gap-1.5 whitespace-nowrap"
                    onClick={() => setConfirmOpen(true)}
                    disabled={empty || downloading}
                >
                    <Trash2 size={12} />
                    Clear archive
                </button>
            </div>

            <Modal
                open={confirmOpen}
                onOpenChange={(open) => {
                    if (!clearing) setConfirmOpen(open)
                }}
                title="Clear the plan archive?"
            >
                <div className="space-y-4">
                    <p className="text-sm text-muted">
                        This deletes all {count} archived planner runs. It cannot be undone. Download the archive first
                        if you still need it.
                    </p>
                    <div className="flex justify-end gap-3">
                        <button
                            type="button"
                            className="btn btn-ghost"
                            onClick={() => setConfirmOpen(false)}
                            disabled={clearing}
                        >
                            Cancel
                        </button>
                        <button type="button" className="btn btn-danger" onClick={confirmClear} disabled={clearing}>
                            {clearing ? 'Clearing…' : 'Yes, clear archive'}
                        </button>
                    </div>
                </div>
            </Modal>
        </Card>
    )
}

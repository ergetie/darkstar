import React, { useState } from 'react'
import { Api } from '../../../lib/api'
import { useToast } from '../../../lib/useToast'
import Modal from '../../../components/ui/Modal'

function firstOfCurrentMonth(): string {
    const now = new Date()
    const month = String(now.getMonth() + 1).padStart(2, '0')
    return `${now.getFullYear()}-${month}-01`
}

/**
 * Reprices historical import prices from the stored spot price with the current
 * pricing settings. Saved settings are used, so unsaved edits are not applied.
 */
export const RecalculateCostsPanel: React.FC<{ disabled?: boolean }> = ({ disabled }) => {
    const { toast } = useToast()
    const [fromDate, setFromDate] = useState(firstOfCurrentMonth)
    const [modalOpen, setModalOpen] = useState(false)
    const [loading, setLoading] = useState(false)

    const handleRecalculate = async () => {
        setLoading(true)
        try {
            const result = await Api.recalculatePrices(fromDate)
            toast({
                message: `Costs recalculated from ${result.from_date}: ${result.repriced} slots repriced, ${result.skipped} skipped`,
                variant: 'success',
            })
            setModalOpen(false)
        } catch (e: unknown) {
            toast({
                message: 'Recalculation failed: ' + (e instanceof Error ? e.message : 'Unknown error'),
                variant: 'error',
            })
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="mt-4 rounded-xl border border-line/40 p-4" data-testid="recalculate-costs">
            <div className="text-xs font-bold text-text">Recalculate costs</div>
            <p className="text-[11px] text-muted mt-1">
                Reprices the recorded import prices from the stored spot price using your saved pricing settings
                (transfer fee, energy tax, supplier markup and VAT). Save your changes first. Existing planner history
                is not repriced, so the learning plan-versus-actual cost metric shows a step at the chosen date.
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-2 text-[11px] text-muted">
                    From
                    <input
                        type="date"
                        value={fromDate}
                        onChange={(e) => setFromDate(e.target.value)}
                        className="bg-surface2/50 border border-line/30 rounded px-2 py-1 text-[11px] text-text focus:outline-none focus:ring-1 focus:ring-accent"
                    />
                </label>
                <button
                    type="button"
                    disabled={disabled || !fromDate}
                    onClick={() => setModalOpen(true)}
                    className="rounded-lg bg-surface2 border border-line/20 px-4 py-2 text-xs font-semibold text-text hover:bg-surface0 transition disabled:opacity-50"
                >
                    {`Recalculate costs from ${fromDate || '…'}`}
                </button>
            </div>

            <Modal open={modalOpen} onOpenChange={setModalOpen} title="Recalculate historical costs?">
                <div className="space-y-4">
                    <p className="text-sm text-muted">
                        This overwrites the recorded import prices from <strong>{fromDate}</strong> onwards using your
                        saved pricing settings. The previous prices are not kept and this cannot be undone.
                    </p>
                    <div className="flex justify-end gap-3 mt-6">
                        <button
                            type="button"
                            onClick={() => setModalOpen(false)}
                            className="px-4 py-2 text-xs font-semibold text-white/70 hover:text-white transition"
                        >
                            Cancel
                        </button>
                        <button
                            type="button"
                            onClick={handleRecalculate}
                            disabled={loading}
                            className="bg-accent hover:bg-accent2 px-4 py-2 rounded-xl text-xs font-bold text-[#100f0e] transition disabled:opacity-50"
                        >
                            {loading ? 'Recalculating...' : 'Yes, Recalculate'}
                        </button>
                    </div>
                </div>
            </Modal>
        </div>
    )
}

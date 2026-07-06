import React from 'react'
import { NumberInput } from '../../../components/ui/NumberInput'

interface ChargerPriorityEditorProps {
    value: string
    onChange: (priorities: Record<string, number>) => void
    disabled?: boolean
    config?: Record<string, unknown>
}

interface CurrentTypeCharger {
    id: string
    name: string
    phases: number[]
}

function parsePriorities(value: string): Record<string, number> {
    try {
        const parsed: unknown = JSON.parse(value || '{}')
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as Record<string, number>) : {}
    } catch {
        return {}
    }
}

export const ChargerPriorityEditor: React.FC<ChargerPriorityEditorProps> = ({
    value,
    onChange,
    disabled = false,
    config,
}) => {
    const priorities = parsePriorities(value)

    const chargers: CurrentTypeCharger[] = (
        (config?.ev_chargers as { id: string; name?: string; type?: string; phases?: number[] }[] | undefined) || []
    )
        .filter((c) => c.type === 'current')
        .map((c) => ({ id: c.id, name: c.name || c.id, phases: c.phases || [1, 2, 3] }))

    const updatePriority = (chargerId: string, priority: number) => {
        onChange({ ...priorities, [chargerId]: priority })
    }

    if (chargers.length === 0) {
        return (
            <div className="text-center py-6 px-4 bg-surface-elevated rounded-xl border border-line/20 border-dashed">
                <div className="text-muted text-sm">
                    No dynamically-throttled chargers configured. Add an EV charger with type: current in the EV tab.
                </div>
            </div>
        )
    }

    return (
        <div className="space-y-2">
            {chargers.map((charger, index) => (
                <div
                    key={charger.id}
                    className="p-3 rounded-xl border border-line/40 bg-surface-elevated flex items-center gap-4"
                >
                    <div className="flex-1">
                        <div className="text-sm font-semibold text-text">{charger.name}</div>
                        <div className="text-[11px] text-muted">
                            Phases: {charger.phases.map((p) => `L${p}`).join(', ')}
                        </div>
                    </div>
                    <div className="w-28">
                        <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">Priority</label>
                        <NumberInput
                            value={priorities[charger.id] ?? index}
                            onChange={(val) => updatePriority(charger.id, Number(val) || 0)}
                            disabled={disabled}
                            step={1}
                            min={0}
                        />
                    </div>
                </div>
            ))}
            <p className="text-[10px] text-muted">
                Lower priority number gives way (throttles fully toward its floor) first when chargers share an
                overloaded phase. With a single charger, priority has no effect.
            </p>
        </div>
    )
}

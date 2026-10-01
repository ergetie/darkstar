import EntitySelect from '../EntitySelect'
import type { EntityCandidate, HaDiscoveryEntity } from '../../lib/api'

type Props = {
    label: string
    value: string
    onChange: (value: string) => void
    entities: HaDiscoveryEntity[]
    candidate?: EntityCandidate
    required?: boolean
    plausibility?: string
}

const confidenceBadge: Record<EntityCandidate['confidence'], string> = {
    high: 'badge-good',
    medium: 'badge-warn',
    low: 'badge-muted',
}

export function EntityField({ label, value, onChange, entities, candidate, required, plausibility }: Props) {
    const liveEntity = entities.find((entity) => entity.entity_id === value)
    const showSuggestion = Boolean(candidate?.entity_id && candidate.entity_id !== value)

    return (
        <div className="space-y-1.5">
            <label className="block text-sm font-semibold text-text">
                {label} {required && <span className="text-bad">*</span>}
            </label>
            <EntitySelect
                entities={entities}
                value={value}
                onChange={onChange}
                placeholder="Select a Home Assistant entity…"
            />
            {liveEntity && (
                <div className="text-xs text-muted" aria-live="polite">
                    Current value: <span className="font-medium text-text">{liveEntity.state ?? 'Unavailable'}</span>
                    {liveEntity.unit_of_measurement ? ` ${liveEntity.unit_of_measurement}` : ''}
                </div>
            )}
            {plausibility && <div className="text-xs text-muted">{plausibility}</div>}
            {candidate && (
                <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span
                        className={`badge ${confidenceBadge[candidate.confidence]}`}
                        title={candidate.reasons.join(', ')}
                    >
                        {candidate.confidence} match
                    </span>
                    {showSuggestion && (
                        <span className="text-muted">
                            Suggested: <code>{candidate.entity_id}</code>
                        </span>
                    )}
                    {showSuggestion && (
                        <button
                            type="button"
                            className="btn btn-ghost px-2 py-1 text-xs"
                            onClick={() => onChange(candidate.entity_id)}
                        >
                            Use suggested
                        </button>
                    )}
                    {value && candidate.entity_id === value && candidate.confidence === 'high' && (
                        <span className="text-good">Auto-detected</span>
                    )}
                </div>
            )}
        </div>
    )
}

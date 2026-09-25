import type { EVChargerEntity } from './components/EntityArrayEditor'

export const DEFAULT_NOMINAL_VOLTAGE_V = 230

/**
 * Derived EV charger power limits, mirroring backend/core/ev_power.py:
 * current chargers: max = max_current_a x phases x V, min = min_current_a x phases x V x 1.01;
 * binary chargers: min = max = rated_power_kw. Returns null when not derivable.
 */
export function evChargerPowerLimits(
    entity: Pick<EVChargerEntity, 'type' | 'rated_power_kw' | 'min_current_a' | 'max_current_a' | 'phases'>,
    voltage: number = DEFAULT_NOMINAL_VOLTAGE_V,
): { minKw: number; maxKw: number } | null {
    if (entity.type === 'current') {
        const maxA = Number(entity.max_current_a)
        const phaseCount = Array.isArray(entity.phases) ? entity.phases.length : 0
        if (!(maxA > 0) || phaseCount <= 0 || !(voltage > 0)) return null
        const minA = Math.min(Number(entity.min_current_a) > 0 ? Number(entity.min_current_a) : 6, maxA)
        const maxKw = (maxA * phaseCount * voltage) / 1000
        const minKw = Math.min(((minA * phaseCount * voltage) / 1000) * 1.01, maxKw)
        return { minKw, maxKw }
    }
    const rated = Number(entity.rated_power_kw)
    return rated > 0 ? { minKw: rated, maxKw: rated } : null
}

/**
 * Why a charger cannot be planned, mirroring backend/core/ev_power.py
 * charger_disabled_reason. Uses the charger's configured name (falling back to
 * its id). Returns null when the power limits are derivable.
 */
export function evChargerDisabledReason(
    entity: Pick<
        EVChargerEntity,
        'id' | 'name' | 'type' | 'rated_power_kw' | 'min_current_a' | 'max_current_a' | 'phases'
    >,
    voltage: number = DEFAULT_NOMINAL_VOLTAGE_V,
): string | null {
    if (evChargerPowerLimits(entity, voltage)) return null
    const name = entity.name || entity.id || 'this charger'
    if (entity.type === 'current') {
        const phaseCount = Array.isArray(entity.phases) ? entity.phases.length : 0
        return phaseCount <= 0
            ? `Configure phases for ${name} to enable planning`
            : `Configure max current for ${name} to enable planning`
    }
    return `Configure rated power for ${name} to enable planning`
}

import { BaseField } from '../types'
import { shouldRenderField } from '../logic'

export interface FieldVisibility {
    hidden: boolean
    hint?: string
}

// Tabs that are entirely gated behind Advanced Mode (see ALL_TABS in settings/index.tsx).
const ADVANCED_ONLY_TABS = new Set(['advanced'])

function humanizeConfigKey(key: string): string {
    const last = key.split('.').pop() || key
    return last.replace(/_/g, ' ')
}

function defaultHint(field: BaseField): string {
    if (field.showIf) {
        return `Requires "${humanizeConfigKey(field.showIf.configKey)}" to be set`
    }
    if (field.showIfAll?.length) {
        return `Requires ${field.showIfAll.map(humanizeConfigKey).join(', ')}`
    }
    if (field.showIfAny?.length) {
        return `Requires one of ${field.showIfAny.map(humanizeConfigKey).join(', ')}`
    }
    return 'Currently hidden'
}

/**
 * Evaluates whether a search result's field is currently rendered, given the
 * live config and advanced-mode state — mirrors the per-tab gating logic
 * (isAdvanced fields, advanced-only tabs, and shouldRenderField's showIf checks).
 */
export function getFieldVisibility(
    field: BaseField,
    tabId: string,
    config: Record<string, unknown> | null,
    advancedMode: boolean,
): FieldVisibility {
    if (ADVANCED_ONLY_TABS.has(tabId) && !advancedMode) {
        return { hidden: true, hint: 'Advanced mode required' }
    }
    if (field.isAdvanced && !advancedMode) {
        return { hidden: true, hint: 'Advanced mode required' }
    }

    const enabled = shouldRenderField(field, {}, config ?? undefined)
    if (!enabled) {
        return { hidden: true, hint: field.showIf?.disabledText || defaultHint(field) }
    }

    return { hidden: false }
}

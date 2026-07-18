import configHelp from '../../../config-help.json'
import {
    systemSections,
    parameterSections,
    solarSections,
    batterySections,
    evSections,
    waterSections,
    loadBalancingSections,
    uiSections,
    advancedSections,
    SettingsSection,
    BaseField,
} from '../types'
import { guides, Guide } from './guides'

export interface SearchFieldEntry {
    tabId: string
    tabLabel: string
    sectionTitle: string
    fieldKey: string
    label: string
    helper?: string
    helpText?: string
    /** The underlying field definition, kept for visibility/hint evaluation. */
    field: BaseField
}

interface TabSectionGroup {
    tabId: string
    tabLabel: string
    sections: SettingsSection[]
}

// Mirrors the tab list in settings/index.tsx (ALL_TABS) and the *Sections
// arrays each tab renders from in types.ts.
const TAB_GROUPS: TabSectionGroup[] = [
    { tabId: 'system', tabLabel: 'System', sections: systemSections },
    { tabId: 'parameters', tabLabel: 'Parameters', sections: parameterSections },
    { tabId: 'solar', tabLabel: 'Solar', sections: solarSections },
    { tabId: 'battery', tabLabel: 'Battery', sections: batterySections },
    { tabId: 'ev', tabLabel: 'EV', sections: evSections },
    { tabId: 'water', tabLabel: 'Heating', sections: waterSections },
    { tabId: 'load-balancing', tabLabel: 'Load Balancing', sections: loadBalancingSections },
    { tabId: 'ui', tabLabel: 'UI', sections: uiSections },
    { tabId: 'advanced', tabLabel: 'Advanced', sections: advancedSections },
]

const helpMap = configHelp as Record<string, string>

function buildFieldIndex(): SearchFieldEntry[] {
    const entries: SearchFieldEntry[] = []
    for (const group of TAB_GROUPS) {
        for (const section of group.sections) {
            for (const field of section.fields) {
                entries.push({
                    tabId: group.tabId,
                    tabLabel: group.tabLabel,
                    sectionTitle: section.title,
                    fieldKey: field.key,
                    label: field.label,
                    helper: field.helper,
                    helpText: helpMap[field.key] || field.helper,
                    field,
                })
            }
        }
    }
    return entries
}

export const fieldSearchIndex: SearchFieldEntry[] = buildFieldIndex()

export interface FieldSearchResult {
    kind: 'field'
    entry: SearchFieldEntry
    score: number
}

export interface GuideSearchResult {
    kind: 'guide'
    guide: Guide
    score: number
}

export type SearchResult = FieldSearchResult | GuideSearchResult

function tokenize(query: string): string[] {
    return query.toLowerCase().trim().split(/\s+/).filter(Boolean)
}

// Every token must match at least one haystack; a token's contribution is the
// highest-weighted haystack it hits, so label matches outrank key/help matches.
function matchScore(haystacks: { text: string | undefined; weight: number }[], tokens: string[]): number {
    let total = 0
    for (const token of tokens) {
        let tokenScore = 0
        for (const { text, weight } of haystacks) {
            if (text && text.toLowerCase().includes(token)) {
                tokenScore = Math.max(tokenScore, weight)
            }
        }
        if (tokenScore === 0) return 0
        total += tokenScore
    }
    return total
}

export function searchFields(query: string): FieldSearchResult[] {
    const tokens = tokenize(query)
    if (tokens.length === 0) return []

    const results: FieldSearchResult[] = []
    for (const entry of fieldSearchIndex) {
        const score = matchScore(
            [
                { text: entry.label, weight: 3 },
                { text: entry.fieldKey, weight: 2 },
                { text: entry.helpText, weight: 1 },
            ],
            tokens,
        )
        if (score > 0) results.push({ kind: 'field', entry, score })
    }
    return results.sort((a, b) => b.score - a.score)
}

export function searchGuides(query: string): GuideSearchResult[] {
    const tokens = tokenize(query)
    if (tokens.length === 0) return []

    const results: GuideSearchResult[] = []
    for (const guide of guides) {
        const score = matchScore(
            [
                { text: guide.title, weight: 3 },
                { text: guide.summary, weight: 2 },
                { text: guide.body, weight: 1 },
            ],
            tokens,
        )
        if (score > 0) results.push({ kind: 'guide', guide, score })
    }
    return results.sort((a, b) => b.score - a.score)
}

export function search(query: string): { fields: FieldSearchResult[]; guides: GuideSearchResult[] } {
    return { fields: searchFields(query), guides: searchGuides(query) }
}

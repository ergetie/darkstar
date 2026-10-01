import { useEffect, useState } from 'react'
import Card from '../../../components/Card'
import { Badge } from '../../../components/ui/Badge'
import { Api, type ProfileSuggestionsResponse } from '../../../lib/api'

interface ProfileSetupHelperProps {
    profileName: string
    currentForm: Record<string, string>
    onApply: (suggestions: Record<string, unknown>) => void
}

function flattenPatch(value: unknown, prefix = '', result: Record<string, unknown> = {}): Record<string, unknown> {
    if (Array.isArray(value)) {
        if (prefix) result[prefix] = value
    } else if (value && typeof value === 'object') {
        Object.entries(value).forEach(([key, nested]) =>
            flattenPatch(nested, prefix ? `${prefix}.${key}` : key, result),
        )
    } else if (prefix) {
        result[prefix] = value
    }
    return result
}

export const ProfileSetupHelper: React.FC<ProfileSetupHelperProps> = ({ profileName, currentForm, onApply }) => {
    const [query, setQuery] = useState<
        | { profileName: string; status: 'loading' }
        | { profileName: string; status: 'loaded'; data: ProfileSuggestionsResponse }
        | { profileName: string; status: 'error'; error: string }
        | null
    >(null)
    const [showDiff, setShowDiff] = useState(false)

    useEffect(() => {
        if (!profileName || profileName === 'generic') {
            return
        }
        let active = true
        Api.profileSuggestions(profileName)
            .then((response) => {
                if (active) setQuery({ profileName, status: 'loaded', data: response })
            })
            .catch((error: unknown) => {
                if (active)
                    setQuery({
                        profileName,
                        status: 'error',
                        error: error instanceof Error ? error.message : 'Could not load profile suggestions.',
                    })
            })
        return () => {
            active = false
        }
    }, [profileName])

    const activeQuery = query?.profileName === profileName ? query : null
    const activeSuggestions = activeQuery?.status === 'loaded' ? activeQuery.data : null
    const errorMsg = activeQuery?.status === 'error' ? activeQuery.error : null
    const loading = activeQuery === null || activeQuery.status === 'loading'
    const rows = activeSuggestions
        ? Object.entries(activeSuggestions.candidates).flatMap(([path, candidates]) => {
              const best = candidates[0]
              if (!best) return []
              const current = currentForm[path] ?? activeSuggestions.current[path]
              if (String(current ?? '') === best.entity_id) return []
              return [{ path, current, suggested: best.entity_id, confidence: best.confidence, reasons: best.reasons }]
          })
        : []

    if (!profileName || profileName === 'generic') return null
    if (loading && !activeSuggestions)
        return <div className="mb-4 text-xs text-muted animate-pulse">Checking profile compatibility…</div>
    if (!activeSuggestions && !errorMsg) return null

    return (
        <Card className="mb-6 overflow-hidden border-accent/20 bg-accent/5">
            <div className="space-y-4 p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                        <div className="text-sm font-bold text-text">Profile setup suggestions</div>
                        <p className="mt-1 text-xs text-muted">
                            Suggestions are matched against Home Assistant entities. Apply only the high-confidence
                            matches you want to use.
                        </p>
                    </div>
                    <Badge variant="info">{profileName}</Badge>
                </div>
                {activeSuggestions?.missing_required.length ? (
                    <div className="banner banner-warning">
                        No match found for: {activeSuggestions.missing_required.join(', ')}
                    </div>
                ) : null}
                {errorMsg && <div className="banner banner-error">{errorMsg}</div>}
                {rows.length > 0 && (
                    <>
                        <div className="flex items-center justify-between gap-3">
                            <span className="text-xs text-muted">
                                {rows.length} differing suggestion{rows.length === 1 ? '' : 's'}
                            </span>
                            <div className="flex gap-2">
                                <button
                                    className="btn btn-secondary"
                                    type="button"
                                    onClick={() => setShowDiff((visible) => !visible)}
                                >
                                    {showDiff ? 'Hide details' : 'View details'}
                                </button>
                                <button
                                    className="btn btn-primary"
                                    type="button"
                                    onClick={() => onApply(flattenPatch(activeSuggestions?.patch))}
                                >
                                    Apply high-confidence suggestions
                                </button>
                            </div>
                        </div>
                        {showDiff && (
                            <div className="overflow-x-auto rounded-ds-md border border-line bg-surface">
                                <table className="w-full text-left text-xs">
                                    <thead>
                                        <tr className="border-b border-line text-muted">
                                            <th className="p-3">Setting</th>
                                            <th className="p-3">Current</th>
                                            <th className="p-3">Suggested</th>
                                            <th className="p-3">Match</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {rows.map((row) => (
                                            <tr className="border-b border-line last:border-0" key={row.path}>
                                                <td className="p-3 font-mono">{row.path}</td>
                                                <td className="p-3">
                                                    {row.current === undefined || row.current === ''
                                                        ? 'Not set'
                                                        : String(row.current)}
                                                </td>
                                                <td className="p-3 font-mono">{row.suggested}</td>
                                                <td className="p-3" title={row.reasons.join(', ')}>
                                                    {row.confidence}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </>
                )}
            </div>
        </Card>
    )
}

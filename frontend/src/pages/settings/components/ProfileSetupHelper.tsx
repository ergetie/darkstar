import React, { useState, useEffect } from 'react'
import Card from '../../../components/Card'
import { Badge } from '../../../components/ui/Badge'
import { motion, AnimatePresence } from 'framer-motion'

interface ProfileSuggestionDiff {
    key: string
    short_key: string
    suggested: unknown
    current: unknown
    is_missing: boolean
    is_different: boolean
}

interface ProfileSuggestionsResponse {
    profile_name: string
    profile_description: string
    suggestions: Record<string, unknown>
    missing_entities: string[]
    diff: ProfileSuggestionDiff[]
}

interface ProfileSetupHelperProps {
    profileName: string
    currentForm: Record<string, string>
    onApply: (suggestions: Record<string, unknown>) => void
}

export const ProfileSetupHelper: React.FC<ProfileSetupHelperProps> = ({ profileName, currentForm, onApply }) => {
    const [loading, setLoading] = useState(false)
    const [suggestions, setSuggestions] = useState<ProfileSuggestionsResponse | null>(null)
    const [errorMsg, setErrorMsg] = useState<string | null>(null)
    const [showDiff, setShowDiff] = useState(false)

    useEffect(() => {
        if (!profileName || profileName === 'generic') {
            return
        }

        const fetchSuggestions = async () => {
            setLoading(true)
            setErrorMsg(null)
            try {
                const response = await fetch(`api/profiles/${profileName}/suggestions`)
                if (!response.ok) {
                    if (response.status === 404) {
                        setSuggestions(null)
                        return
                    }
                    throw new Error('Failed to fetch profile suggestions')
                }
                const data = await response.json()
                setSuggestions(data)
            } catch (err) {
                console.error('Error fetching suggestions:', err)
                setErrorMsg(err instanceof Error ? err.message : 'Unknown error')
            } finally {
                setLoading(false)
            }
        }

        fetchSuggestions()
    }, [profileName])

    // Generic profile has no suggestions to show, even if a previous profile's fetch is still cached in state
    const isGeneric = !profileName || profileName === 'generic'
    const displaySuggestions = isGeneric ? null : suggestions

    // Calculate diffs using local form state (if available)
    const diffItems = displaySuggestions
        ? displaySuggestions.diff.filter((d) => {
              // Check if locally applied
              const localValue = currentForm ? currentForm[d.key] : undefined
              if (localValue !== undefined) {
                  // Compare as strings to handle different types
                  return String(localValue) !== String(d.suggested)
              }
              return d.is_different || d.is_missing
          })
        : []

    if (!displaySuggestions || (!displaySuggestions.missing_entities.length && !diffItems.length)) {
        if (!isGeneric && loading)
            return <div className="text-xs text-muted animate-pulse">Checking profile compatibility...</div>
        return null
    }

    return (
        <Card className="mb-6 overflow-hidden border-accent/20 bg-accent/5">
            <div className="p-5">
                <div className="flex items-start justify-between gap-4">
                    <div className="flex items-center gap-3">
                        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent/20 text-xl">
                            💡
                        </div>
                        <div>
                            <div className="text-sm font-bold text-text">Profile Setup Helper</div>
                            <div className="text-xs text-muted mt-0.5">
                                Optimize your configuration for the{' '}
                                <span className="text-accent font-semibold">{displaySuggestions.profile_name}</span>{' '}
                                profile.
                            </div>
                        </div>
                    </div>
                    <Badge variant="info">Optimization Available</Badge>
                </div>

                <div className="mt-4 space-y-3">
                    {displaySuggestions.missing_entities.length > 0 && (
                        <div className="rounded-lg bg-bad/10 border border-bad/20 p-3">
                            <div className="text-[11px] font-bold text-bad uppercase tracking-wider flex items-center gap-2">
                                <span className="w-1.5 h-1.5 rounded-full bg-bad animate-pulse" />
                                Missing Required Entities
                            </div>
                            <ul className="mt-2 space-y-1">
                                {displaySuggestions.missing_entities.map((key) => (
                                    <li key={key} className="text-xs text-muted flex items-center gap-2">
                                        <code className="bg-surface1 px-1 py-0.5 rounded text-[10px]">{key}</code>
                                        <span>is not configured.</span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}

                    <div className="flex items-center justify-between gap-4 py-2">
                        <p className="text-xs text-muted max-w-md">
                            We found {diffItems.length} settings that can be automatically updated to match the
                            recommended configuration for your inverter.
                        </p>
                        <div className="flex gap-2">
                            <button
                                onClick={() => setShowDiff(!showDiff)}
                                className="rounded-lg px-3 py-1.5 text-[10px] font-bold bg-surface1 hover:bg-surface2 transition text-text border border-line/30"
                            >
                                {showDiff ? 'Hide Details' : 'View Details'}
                            </button>
                            <button
                                onClick={() => onApply(displaySuggestions.suggestions)}
                                className="rounded-lg px-3 py-1.5 text-[10px] font-bold bg-accent hover:bg-accent2 transition text-[#100f0e] btn-glow-primary shadow-lg shadow-accent/20"
                            >
                                Apply Recommendations
                            </button>
                        </div>
                    </div>

                    <AnimatePresence>
                        {showDiff && (
                            <motion.div
                                initial={{ opacity: 0, height: 0 }}
                                animate={{ opacity: 1, height: 'auto' }}
                                exit={{ opacity: 0, height: 0 }}
                                className="overflow-hidden"
                            >
                                <div className="mt-4 rounded-xl border border-line/30 bg-surface1/50 overflow-hidden">
                                    <table className="w-full text-left text-xs">
                                        <thead>
                                            <tr className="bg-surface1 text-muted uppercase tracking-wider text-[10px] font-bold">
                                                <th className="px-4 py-2">Setting</th>
                                                <th className="px-4 py-2">Current</th>
                                                <th className="px-4 py-2">Recommended</th>
                                            </tr>
                                        </thead>
                                        <tbody className="divide-y divide-line/10">
                                            {diffItems.map((item) => (
                                                <tr key={item.key} className="hover:bg-surface2/50 transition">
                                                    <td className="px-4 py-3">
                                                        <div className="font-semibold text-text">{item.short_key}</div>
                                                        <div className="text-[10px] text-muted opacity-60 font-mono">
                                                            {item.key}
                                                        </div>
                                                    </td>
                                                    <td className="px-4 py-3">
                                                        {item.is_missing ? (
                                                            <span className="text-bad font-medium italic">Not set</span>
                                                        ) : (
                                                            <code className="text-[10px] bg-bad/5 text-bad/80 px-1 py-0.5 rounded line-through">
                                                                {String(item.current)}
                                                            </code>
                                                        )}
                                                    </td>
                                                    <td className="px-4 py-3">
                                                        <code className="text-[10px] bg-good/10 text-good px-1 py-0.5 rounded font-bold">
                                                            {String(item.suggested)}
                                                        </code>
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                                {errorMsg && (
                                    <div className="text-[10px] text-bad bg-bad/5 px-2 py-1 rounded border border-bad/20">
                                        Error: {errorMsg}
                                    </div>
                                )}
                            </motion.div>
                        )}
                    </AnimatePresence>
                </div>
            </div>
        </Card>
    )
}

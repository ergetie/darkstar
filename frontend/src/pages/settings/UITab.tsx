import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell } from 'lucide-react'
import { Api } from '../../lib/api'
// ThemeInfo commented out - Accent Theme card is hidden
// import { ThemeInfo } from '../../lib/api'
import Card from '../../components/Card'
import { useSettingsForm } from './hooks/useSettingsForm'
import { SettingsField } from './components/SettingsField'
import { uiFieldList, uiSections } from './types'
import { listChangedFields } from './utils'
import { shouldRenderField } from './logic'
import { motion, AnimatePresence } from 'framer-motion'
import { AdditionalAdvancedNotice, GlobalAdvancedLockedNotice } from './components/AdvancedLockedNotice'
import { UnsavedChangesBanner } from './components/UnsavedChangesBanner'
import { NavigationBlockerDialog } from './components/NavigationBlockerDialog'
import { useUnsavedChangesGuard } from './hooks/useUnsavedChangesGuard'

export const UITab: React.FC<{ advancedMode?: boolean }> = ({ advancedMode }) => {
    const navigate = useNavigate()
    const { config, form, fields, fieldErrors, loading, saving, statusMessage, handleChange, save, isDirty } =
        useSettingsForm(uiFieldList, [])

    const blocker = useUnsavedChangesGuard(isDirty)

    const [testingNotification, setTestingNotification] = useState(false)
    const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)

    const handleTestNotification = async () => {
        setTestingNotification(true)
        setTestResult(null)
        try {
            const res = await Api.executor.testNotification()
            setTestResult({ success: res.status === 'success', message: res.message || 'Test sent!' })
        } catch (e) {
            setTestResult({ success: false, message: e instanceof Error ? e.message : 'Test failed' })
        } finally {
            setTestingNotification(false)
        }
    }

    // Themes state commented out - Accent Theme card is hidden
    // const [themes, setThemes] = useState<ThemeInfo[]>([])

    // useEffect(() => {
    //     Api.theme().then((res) => setThemes(res.themes))
    // }, [])

    if (loading) {
        return <Card className="p-6 text-sm text-muted">Loading UI configuration…</Card>
    }

    const fieldVariants = {
        initial: { opacity: 0, y: -10, height: 0 },
        animate: { opacity: 1, y: 0, height: 'auto' },
        exit: { opacity: 0, y: -10, height: 0 },
    }

    // const currentThemeIdx = config?.ui?.theme_accent_index ?? 0

    const hasHiddenSections = uiSections.some((s) => s.fields.every((f) => f.isAdvanced))

    return (
        <div className="space-y-4">
            <UnsavedChangesBanner visible={isDirty} onSave={() => save()} saving={saving} />

            {/* Accent Theme Card - Hidden as per user request */}
            {/* ... */}

            {uiSections.map((section) => {
                const isEntirelyAdvanced = section.fields.every((f) => f.isAdvanced)
                const shouldShowCard = advancedMode || !isEntirelyAdvanced

                return (
                    <AnimatePresence key={section.title} initial={false}>
                        {shouldShowCard && (
                            <motion.div
                                initial={{ opacity: 0, height: 0 }}
                                animate={{ opacity: 1, height: 'auto' }}
                                exit={{ opacity: 0, height: 0 }}
                                transition={{ duration: 0.3 }}
                                className="overflow-visible pb-4"
                            >
                                <Card className="p-6 mb-4">
                                    <div className="flex items-baseline justify-between gap-2">
                                        <div>
                                            <div className="text-sm font-semibold">{section.title}</div>
                                            <p className="text-xs text-muted mt-1">{section.description}</p>
                                        </div>
                                        <span className="text-[10px] uppercase text-muted tracking-wide">
                                            Interface
                                        </span>
                                    </div>
                                    <div className="mt-5 grid gap-4 sm:grid-cols-2">
                                        <AnimatePresence initial={false}>
                                            {section.fields.map(
                                                (field) =>
                                                    (advancedMode || !field.isAdvanced) &&
                                                    shouldRenderField(field, form) && (
                                                        <motion.div
                                                            key={field.key}
                                                            variants={fieldVariants}
                                                            initial="initial"
                                                            animate="animate"
                                                            exit="exit"
                                                            transition={{ duration: 0.2, ease: 'easeOut' }}
                                                            className={`overflow-visible pb-4 ${field.className || ''}`}
                                                        >
                                                            <SettingsField
                                                                field={field}
                                                                value={form[field.key] ?? ''}
                                                                onChange={handleChange}
                                                                error={fieldErrors[field.key]}
                                                                fullForm={form}
                                                            />
                                                        </motion.div>
                                                    ),
                                            )}

                                            {!advancedMode &&
                                                section.fields.some((f) => f.isAdvanced) &&
                                                section.fields.some((f) => !f.isAdvanced) && (
                                                    <motion.div
                                                        key={`${section.title}-additional`}
                                                        variants={fieldVariants}
                                                        initial="initial"
                                                        animate="animate"
                                                        exit="exit"
                                                        className="col-span-2 overflow-hidden"
                                                    >
                                                        <AdditionalAdvancedNotice />
                                                    </motion.div>
                                                )}
                                        </AnimatePresence>
                                    </div>

                                    {section.title === 'Notifications' && (
                                        <div className="mt-4 pt-3 border-t border-line/30">
                                            <button
                                                onClick={handleTestNotification}
                                                disabled={testingNotification}
                                                className={`flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 border text-[11px] font-medium transition-all ${
                                                    testingNotification
                                                        ? 'bg-surface2/50 border-line/30 text-muted cursor-not-allowed'
                                                        : 'bg-accent/10 border-accent/30 text-accent hover:bg-accent/20'
                                                }`}
                                            >
                                                {testingNotification ? (
                                                    <>
                                                        <div className="h-3 w-3 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
                                                        Sending…
                                                    </>
                                                ) : (
                                                    <>
                                                        <Bell className="h-3.5 w-3.5" />
                                                        Send Test Notification
                                                    </>
                                                )}
                                            </button>

                                            {testResult && (
                                                <div
                                                    className={`mt-2 text-[11px] ${testResult.success ? 'text-good' : 'text-bad'}`}
                                                >
                                                    {testResult.message}
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </Card>
                            </motion.div>
                        )}
                    </AnimatePresence>
                )
            })}

            {!advancedMode && hasHiddenSections && <GlobalAdvancedLockedNotice />}

            <div className="flex flex-wrap items-center gap-3">
                <button
                    disabled={saving}
                    onClick={() => save()}
                    className="flex items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-[11px] font-semibold transition btn-glow-primary bg-accent hover:bg-accent2 text-[#100f0e] disabled:opacity-50"
                >
                    {saving ? 'Saving…' : 'Save UI Settings'}
                </button>
                {statusMessage && (
                    <div
                        className={`rounded-lg p-3 text-sm ${
                            statusMessage.startsWith('Please fix') ||
                            statusMessage.startsWith('Save failed') ||
                            statusMessage.startsWith('Failed to load')
                                ? 'bg-bad/10 border border-bad/30 text-bad'
                                : 'bg-good/10 border border-good/30 text-good'
                        }`}
                    >
                        {statusMessage}
                    </div>
                )}
            </div>

            <NavigationBlockerDialog
                visible={blocker.state === 'blocked'}
                onStay={() => blocker.reset?.()}
                onLeave={() => {
                    if (blocker.location) {
                        navigate(blocker.location.pathname + blocker.location.search, {
                            state: { ...blocker.location.state, ignoreUnsavedChangesGuard: true },
                        })
                    }
                }}
                changes={config ? listChangedFields(config as unknown as Record<string, unknown>, form, fields) : []}
            />
        </div>
    )
}

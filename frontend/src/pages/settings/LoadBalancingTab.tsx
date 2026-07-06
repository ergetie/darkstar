import React from 'react'
import { useNavigate } from 'react-router-dom'
import Card from '../../components/Card'
import { useSettingsForm } from './hooks/useSettingsForm'
import { SettingsField } from './components/SettingsField'
import { loadBalancingFieldList, loadBalancingSections } from './types'
import { isPowerModeEntity, shouldRenderField } from './logic'
import { motion, AnimatePresence } from 'framer-motion'
import { AdditionalAdvancedNotice, GlobalAdvancedLockedNotice } from './components/AdvancedLockedNotice'
import { UnsavedChangesBanner } from './components/UnsavedChangesBanner'
import { NavigationBlockerDialog } from './components/NavigationBlockerDialog'
import { useUnsavedChangesGuard } from './hooks/useUnsavedChangesGuard'

export const LoadBalancingTab: React.FC<{ advancedMode?: boolean }> = ({ advancedMode }) => {
    const navigate = useNavigate()
    const {
        config,
        form,
        fieldErrors,
        loading,
        saving,
        statusMessage,
        handleChange,
        save,
        isDirty,
        haEntities,
        haLoading,
    } = useSettingsForm(loadBalancingFieldList, [])

    const blocker = useUnsavedChangesGuard(isDirty)
    const hasHiddenSections = loadBalancingSections.some((s) => s.fields.every((f) => f.isAdvanced))

    const anyPhasePowerMode = ['l1', 'l2', 'l3'].some((phase) =>
        isPowerModeEntity(form[`input_sensors.grid_current_${phase}`], haEntities),
    )
    const formWithComputed = {
        ...form,
        '_computed.any_phase_power_mode': anyPhasePowerMode ? 'true' : 'false',
    }

    // Slow-tick warning (load-balancing-completion 6.4): the balancer reacts
    // and reports only once per executor tick.
    const executorIntervalSeconds = Number(
        ((config as Record<string, unknown> | null)?.executor as Record<string, unknown> | undefined)
            ?.interval_seconds ?? 300,
    )
    const showSlowTickWarning = form['load_balancing.enabled'] === 'true' && executorIntervalSeconds > 15

    if (loading) {
        return <Card className="p-6 text-sm text-muted">Loading load balancing configuration…</Card>
    }

    const fieldVariants = {
        initial: { opacity: 0, y: -10, height: 0 },
        animate: { opacity: 1, y: 0, height: 'auto' },
        exit: { opacity: 0, y: -10, height: 0 },
    }

    return (
        <div className="space-y-4">
            <UnsavedChangesBanner visible={isDirty} onSave={() => save()} saving={saving} />

            {showSlowTickWarning && (
                <div role="alert" className="rounded-xl border border-accent/40 bg-accent/10 p-3 text-sm text-text">
                    <span className="font-semibold">Executor tick is too slow for load balancing:</span>{' '}
                    <code className="text-xs">executor.interval_seconds</code> is {executorIntervalSeconds} s, so the
                    balancer reacts to an overload (and updates its status) only once every {executorIntervalSeconds}{' '}
                    seconds. With <code className="text-xs">load_balancing.enabled</code> on, set the executor interval
                    to 15 s or less (5 s typical) in the Advanced tab.
                </div>
            )}

            {loadBalancingSections.map((section) => {
                const isEntirelyAdvanced = section.fields.every((f) => f.isAdvanced)
                const shouldShowCard = advancedMode || !isEntirelyAdvanced

                if (!shouldShowCard) return null

                return (
                    <AnimatePresence key={section.title} initial={false}>
                        <motion.div
                            variants={fieldVariants}
                            initial="initial"
                            animate="animate"
                            exit="exit"
                            transition={{ duration: 0.2 }}
                        >
                            <Card className="overflow-hidden">
                                <div className="px-6 py-4">
                                    <h2 className="text-lg font-semibold text-foreground">{section.title}</h2>
                                    {section.description && (
                                        <p className="mt-1 text-sm text-muted">{section.description}</p>
                                    )}
                                </div>
                                <div className="grid grid-cols-1 gap-4 p-6 md:grid-cols-2">
                                    {section.fields.map((field) => {
                                        if (
                                            !shouldRenderField(
                                                field,
                                                formWithComputed,
                                                config as Record<string, unknown>,
                                            )
                                        )
                                            return null
                                        return (
                                            <SettingsField
                                                key={field.key}
                                                field={field}
                                                value={form[field.key]}
                                                onChange={handleChange}
                                                error={fieldErrors[field.key]}
                                                haEntities={haEntities}
                                                haLoading={haLoading}
                                                fullForm={formWithComputed}
                                                config={config as Record<string, unknown>}
                                            />
                                        )
                                    })}
                                </div>
                            </Card>
                        </motion.div>
                    </AnimatePresence>
                )
            })}

            <AdditionalAdvancedNotice visible={!advancedMode} />

            <div className="flex flex-wrap items-center gap-3">
                <button
                    disabled={saving}
                    onClick={() => save()}
                    className="flex items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-[11px] font-semibold transition btn-glow-primary bg-accent hover:bg-accent2 text-[#100f0e] disabled:opacity-50"
                >
                    {saving ? 'Saving…' : 'Save Load Balancing Settings'}
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
            />

            {!advancedMode && hasHiddenSections && <GlobalAdvancedLockedNotice />}
        </div>
    )
}

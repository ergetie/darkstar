import React from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { AlertTriangle } from 'lucide-react'
import { ChangedField } from '../utils'

interface NavigationBlockerDialogProps {
    visible: boolean
    onStay: () => void
    onLeave: () => void
    changes?: ChangedField[]
}

export const NavigationBlockerDialog: React.FC<NavigationBlockerDialogProps> = ({
    visible,
    onStay,
    onLeave,
    changes,
}) => {
    if (!visible) return null

    return createPortal(
        <AnimatePresence>
            {visible && (
                <motion.div
                    className="modal-overlay"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    onClick={onStay}
                >
                    <motion.div
                        className="modal w-full max-w-sm"
                        initial={{ scale: 0.95, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        exit={{ scale: 0.95, opacity: 0 }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div className="flex flex-col items-center text-center gap-4">
                            <div className="flex items-center justify-center w-12 h-12 rounded-full bg-warn/20 text-warn">
                                <AlertTriangle size={24} />
                            </div>
                            <div>
                                <h3 className="text-lg font-bold text-text">Unsaved Changes</h3>
                                <p className="text-sm text-muted mt-1">
                                    You have unsaved changes. Are you sure you want to leave without saving?
                                </p>
                            </div>
                            {changes && changes.length > 0 && (
                                <div className="w-full max-h-40 overflow-y-auto rounded-lg border border-line/30 bg-surface2/40 p-2 text-left">
                                    {changes.map((change) => (
                                        <div
                                            key={change.key}
                                            className="flex items-center justify-between gap-2 py-1 text-xs border-b border-line/20 last:border-b-0"
                                        >
                                            <span className="text-muted shrink-0">{change.label}</span>
                                            <span className="text-text text-right truncate">
                                                {change.oldValue} → {change.newValue}
                                            </span>
                                        </div>
                                    ))}
                                </div>
                            )}
                            <div className="flex gap-3 w-full mt-2">
                                <button onClick={onStay} className="flex-1 btn btn-secondary btn-lg rounded-xl">
                                    Stay
                                </button>
                                <button onClick={onLeave} className="flex-1 btn btn-danger btn-lg rounded-xl">
                                    Discard & Leave
                                </button>
                            </div>
                        </div>
                    </motion.div>
                </motion.div>
            )}
        </AnimatePresence>,
        document.body,
    )
}

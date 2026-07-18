import React from 'react'
import Modal from '../../../components/ui/Modal'
import { Guide } from './guides'
import { fieldSearchIndex } from './index'

interface GuideViewerProps {
    guide: Guide | null
    onClose: () => void
    onJumpToField: (tabId: string, fieldKey: string) => void
}

export const GuideViewer: React.FC<GuideViewerProps> = ({ guide, onClose, onJumpToField }) => {
    return (
        <Modal open={!!guide} onOpenChange={(open) => !open && onClose()} title={guide?.title} size="lg">
            {guide && (
                <div className="space-y-4">
                    <p className="text-sm text-muted italic">{guide.summary}</p>
                    <div className="text-sm text-text leading-relaxed whitespace-pre-line">{guide.body}</div>
                    <div>
                        <div className="text-[10px] font-bold uppercase tracking-wider text-muted mb-2">
                            Related Settings
                        </div>
                        <div className="flex flex-wrap gap-2">
                            {guide.relatedFieldKeys.map((key) => {
                                const entry = fieldSearchIndex.find((e) => e.fieldKey === key)
                                if (!entry) return null
                                return (
                                    <button
                                        key={key}
                                        type="button"
                                        onClick={() => {
                                            onClose()
                                            onJumpToField(entry.tabId, entry.fieldKey)
                                        }}
                                        className="rounded-lg border border-line/50 bg-surface2 px-3 py-1.5 text-xs font-medium text-text hover:border-accent/50 hover:text-accent transition-colors"
                                    >
                                        {entry.label}
                                        <span className="ml-1.5 text-muted">· {entry.tabLabel}</span>
                                    </button>
                                )
                            })}
                        </div>
                    </div>
                </div>
            )}
        </Modal>
    )
}

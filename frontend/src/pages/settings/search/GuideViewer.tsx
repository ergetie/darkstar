import React from 'react'
import { BookOpen } from 'lucide-react'
import Modal from '../../../components/ui/Modal'
import { Guide } from './guides'
import { ViewerContent } from './viewerContent'
import { fieldSearchIndex } from './index'

interface GuideViewerProps {
    content: ViewerContent | null
    onClose: () => void
    onJumpToField: (tabId: string, fieldKey: string) => void
    onOpenGuide: (guide: Guide) => void
}

export const GuideViewer: React.FC<GuideViewerProps> = ({ content, onClose, onJumpToField, onOpenGuide }) => {
    return (
        <Modal open={!!content} onOpenChange={(open) => !open && onClose()} title={content?.title} size="lg">
            {content && (
                <div className="space-y-4">
                    {content.summary && <p className="text-sm text-muted italic">{content.summary}</p>}
                    <div className="text-sm text-text leading-relaxed whitespace-pre-line">{content.body}</div>
                    {content.relatedFieldKeys.length > 0 && (
                        <div>
                            <div className="text-[10px] font-bold uppercase tracking-wider text-muted mb-2">
                                Related Settings
                            </div>
                            <div className="flex flex-wrap gap-2">
                                {content.relatedFieldKeys.map((key) => {
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
                    )}
                    {content.relatedGuides.length > 0 && (
                        <div>
                            <div className="text-[10px] font-bold uppercase tracking-wider text-muted mb-2">
                                Related Guides
                            </div>
                            <div className="flex flex-wrap gap-2">
                                {content.relatedGuides.map((guide) => (
                                    <button
                                        key={guide.id}
                                        type="button"
                                        onClick={() => onOpenGuide(guide)}
                                        className="flex items-center gap-1.5 rounded-lg border border-line/50 bg-surface2 px-3 py-1.5 text-xs font-medium text-text hover:border-accent/50 hover:text-accent transition-colors"
                                    >
                                        <BookOpen size={12} className="text-accent" />
                                        {guide.title}
                                    </button>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </Modal>
    )
}

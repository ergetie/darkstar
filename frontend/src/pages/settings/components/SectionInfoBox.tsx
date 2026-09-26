import React, { useId, useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import type { SettingsSection } from '../types'

type InfoBox = NonNullable<SettingsSection['infoBox']>

/**
 * Plain-language section explainer rendered as a design-system info banner.
 * With a `tldr`, only that one line shows until the user expands it; without
 * one, the full text is always shown.
 */
export const SectionInfoBox: React.FC<{ infoBox: InfoBox }> = ({ infoBox }) => {
    const collapsible = Boolean(infoBox.tldr)
    const [expanded, setExpanded] = useState(!collapsible)
    const detailsId = useId()

    return (
        <div className="banner banner-info mt-3 mb-0 flex-col items-start gap-1.5" role="note">
            {collapsible ? (
                <button
                    type="button"
                    onClick={() => setExpanded((open) => !open)}
                    aria-expanded={expanded}
                    aria-controls={detailsId}
                    className="flex w-full items-start justify-between gap-2 text-left"
                >
                    <span className="text-xs">
                        <span className="font-semibold">{infoBox.title}</span>
                        <span className="block leading-relaxed">{infoBox.tldr}</span>
                    </span>
                    <span className="flex shrink-0 items-center gap-1 text-[11px] font-semibold">
                        {expanded ? 'Less' : 'More'}
                        {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    </span>
                </button>
            ) : (
                <p className="text-xs font-semibold">{infoBox.title}</p>
            )}
            <div id={detailsId} className={expanded ? 'flex flex-col gap-1.5' : undefined} hidden={!expanded}>
                {infoBox.paragraphs.map((paragraph) => (
                    <p key={paragraph} className="text-xs leading-relaxed">
                        {paragraph}
                    </p>
                ))}
            </div>
        </div>
    )
}

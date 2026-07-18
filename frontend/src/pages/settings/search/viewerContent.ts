import { Guide, guides } from './guides'
import { GlossaryEntry } from './glossary'

/** Common shape the viewer renders — guides and glossary entries both adapt to it. */
export interface ViewerContent {
    title: string
    summary?: string
    body: string
    relatedFieldKeys: string[]
    relatedGuides: Guide[]
}

export function guideToContent(guide: Guide): ViewerContent {
    return {
        title: guide.title,
        summary: guide.summary,
        body: guide.body,
        relatedFieldKeys: guide.relatedFieldKeys,
        relatedGuides: [],
    }
}

export function glossaryToContent(entry: GlossaryEntry): ViewerContent {
    return {
        title: entry.term,
        body: entry.definition,
        relatedFieldKeys: entry.relatedFieldKeys ?? [],
        relatedGuides: (entry.relatedGuideIds ?? [])
            .map((id) => guides.find((g) => g.id === id))
            .filter((g): g is Guide => !!g),
    }
}

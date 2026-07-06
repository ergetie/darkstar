import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import OrderedListEditor from './OrderedListEditor'

type Item = { id: string; label: string }

const ITEMS: Item[] = [
    { id: 'a', label: 'Alpha' },
    { id: 'b', label: 'Beta' },
    { id: 'c', label: 'Gamma' },
]

function renderEditor(onReorder = vi.fn(), items = ITEMS, disabled = false) {
    render(
        <OrderedListEditor
            items={items}
            keyFor={(i) => i.id}
            renderItem={(i) => <span>{i.label}</span>}
            onReorder={onReorder}
            disabled={disabled}
            itemLabel="entry"
        />,
    )
    return onReorder
}

describe('OrderedListEditor', () => {
    it('renders caller-supplied row content in order', () => {
        renderEditor()
        const rows = screen.getAllByRole('listitem')
        expect(rows).toHaveLength(3)
        expect(rows[0]).toHaveTextContent('Alpha')
        expect(rows[2]).toHaveTextContent('Gamma')
    })

    it('moves an item up via the always-available button', () => {
        const onReorder = renderEditor()
        fireEvent.click(screen.getAllByLabelText('Move entry up')[1])
        expect(onReorder).toHaveBeenCalledWith([
            { id: 'b', label: 'Beta' },
            { id: 'a', label: 'Alpha' },
            { id: 'c', label: 'Gamma' },
        ])
    })

    it('moves an item down via the button', () => {
        const onReorder = renderEditor()
        fireEvent.click(screen.getAllByLabelText('Move entry down')[0])
        expect(onReorder).toHaveBeenCalledWith([
            { id: 'b', label: 'Beta' },
            { id: 'a', label: 'Alpha' },
            { id: 'c', label: 'Gamma' },
        ])
    })

    it('disables the boundary buttons (first up, last down)', () => {
        renderEditor()
        expect(screen.getAllByLabelText('Move entry up')[0]).toBeDisabled()
        expect(screen.getAllByLabelText('Move entry down')[2]).toBeDisabled()
    })

    it('reorders via drag and drop', () => {
        const onReorder = renderEditor()
        const rows = screen.getAllByRole('listitem')
        fireEvent.dragStart(rows[0], { dataTransfer: { effectAllowed: 'move' } })
        fireEvent.dragOver(rows[2])
        fireEvent.drop(rows[2])
        expect(onReorder).toHaveBeenCalledWith([
            { id: 'b', label: 'Beta' },
            { id: 'c', label: 'Gamma' },
            { id: 'a', label: 'Alpha' },
        ])
    })

    it('does not reorder while disabled', () => {
        const onReorder = vi.fn()
        renderEditor(onReorder, ITEMS, true)
        expect(screen.getAllByLabelText('Move entry up')[1]).toBeDisabled()
        expect(screen.getAllByLabelText('Move entry down')[0]).toBeDisabled()
        expect(onReorder).not.toHaveBeenCalled()
    })
})

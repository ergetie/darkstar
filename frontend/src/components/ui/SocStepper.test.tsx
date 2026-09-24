import { useState } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import SocStepper from './SocStepper'
import { clampSoc, parseSocInput } from './socStepper'

function Harness({ initial = 50, min = 0, max = 100 }: { initial?: number; min?: number; max?: number }) {
    const [value, setValue] = useState(initial)
    return <SocStepper value={value} min={min} max={max} onChange={setValue} label="Target" />
}

const valueButton = () => screen.getByRole('button', { name: /tap to type/ })

describe('SocStepper', () => {
    it('increments by 15 and clamps at max', () => {
        render(<Harness initial={50} />)
        fireEvent.click(screen.getByLabelText('Increase Target'))
        expect(valueButton()).toHaveTextContent('65%')

        fireEvent.click(screen.getByLabelText('Increase Target'))
        fireEvent.click(screen.getByLabelText('Increase Target'))
        expect(valueButton()).toHaveTextContent('95%')
        fireEvent.click(screen.getByLabelText('Increase Target'))
        expect(valueButton()).toHaveTextContent('100%')
        expect(screen.getByLabelText('Increase Target')).toBeDisabled()
    })

    it('decrements by 15 and clamps at min', () => {
        render(<Harness initial={20} min={12} />)
        fireEvent.click(screen.getByLabelText('Decrease Target'))
        expect(valueButton()).toHaveTextContent('12%')
        expect(screen.getByLabelText('Decrease Target')).toBeDisabled()
    })

    it('accepts an exact typed value on Enter', () => {
        render(<Harness initial={50} />)
        fireEvent.click(valueButton())
        const input = screen.getByRole('spinbutton', { name: 'Target' })
        fireEvent.change(input, { target: { value: '72' } })
        fireEvent.keyDown(input, { key: 'Enter' })
        expect(valueButton()).toHaveTextContent('72%')
    })

    it('commits on blur', () => {
        render(<Harness initial={50} />)
        fireEvent.click(valueButton())
        const input = screen.getByRole('spinbutton', { name: 'Target' })
        fireEvent.change(input, { target: { value: '33' } })
        fireEvent.blur(input)
        expect(valueButton()).toHaveTextContent('33%')
    })

    it('keeps the old value for invalid input', () => {
        render(<Harness initial={50} min={10} />)
        for (const bad of ['5', '101', 'abc', '7.5', '']) {
            fireEvent.click(valueButton())
            const input = screen.getByRole('spinbutton', { name: 'Target' })
            fireEvent.change(input, { target: { value: bad } })
            fireEvent.keyDown(input, { key: 'Enter' })
            expect(valueButton()).toHaveTextContent('50%')
        }
    })

    it('cancels on Escape', () => {
        render(<Harness initial={50} />)
        fireEvent.click(valueButton())
        const input = screen.getByRole('spinbutton', { name: 'Target' })
        fireEvent.change(input, { target: { value: '80' } })
        fireEvent.keyDown(input, { key: 'Escape' })
        expect(valueButton()).toHaveTextContent('50%')
    })
})

describe('SocStepper helpers', () => {
    it('clampSoc', () => {
        expect(clampSoc(110, 1, 100)).toBe(100)
        expect(clampSoc(-5, 1, 100)).toBe(1)
        expect(clampSoc(64.6, 1, 100)).toBe(65)
    })

    it('parseSocInput', () => {
        expect(parseSocInput(' 72 ', 1, 100)).toBe(72)
        expect(parseSocInput('0', 1, 100)).toBeNull()
        expect(parseSocInput('1e2', 1, 100)).toBeNull()
    })
})

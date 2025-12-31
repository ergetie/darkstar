interface SwitchProps {
    checked: boolean
    onCheckedChange: (checked: boolean) => void
    disabled?: boolean
    className?: string
}

export default function Switch({ checked, onCheckedChange, disabled = false, className = '' }: SwitchProps) {
    return (
        <div
            className={`toggle ${checked ? 'active' : ''} ${className} ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
            onClick={() => !disabled && onCheckedChange(!checked)}
        >
            <div className="toggle-knob" />
        </div>
    )
}

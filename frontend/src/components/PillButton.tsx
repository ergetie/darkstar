export default function PillButton({label, color='#F5D547', onClick}:{
    label: string; color?: string; onClick?: () => void
}){
    return (
        <button
        className="rounded-pill px-3 py-2 text-[12px] font-medium shadow-float border border-line/60"
        onClick={onClick}
        style={{ backgroundColor: color, color: '#0f1216' }}
        >
        {label}
        </button>
    )
}

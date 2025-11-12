export default function PillButton({label, color='#F5D547'}:{
    label: string; color?: string
}){
    return (
        <button
        className="rounded-pill px-3 py-2 text-[12px] font-medium shadow-float border border-line/60"
        style={{ backgroundColor: color, color: '#0f1216' }}
        >
        {label}
        </button>
    )
}

export default function Kpi({label, value, hint}:{label:string; value:string; hint?:string}) {
    return (
        <div className="rounded-xl2 bg-surface2 border border-line/60 px-4 py-3">
        <div className="text-[11px] text-muted tracking-wide">{label}</div>
        <div className="text-lg leading-tight">{value}</div>
        {hint && <div className="text-[11px] text-muted mt-1">{hint}</div>}
        </div>
    )
}

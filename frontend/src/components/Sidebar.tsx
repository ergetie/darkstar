import { Gauge, CalendarRange, BookOpenCheck, Bug, Settings } from 'lucide-react'
import { NavLink } from 'react-router-dom'

const Item = ({to, icon:Icon, label}:{to:string; icon:any; label:string}) => (
    <NavLink
    to={to}
    className={({isActive}) =>
    `group relative flex items-center justify-center w-12 h-12 rounded-2xl border border-line/70
    bg-surface/80 hover:bg-surface2 transition ${isActive ? 'ring-2 ring-accent/50' : ''}`
    }
    title={label}
    >
    <Icon className="h-5 w-5 text-muted group-hover:text-text" />
    <span className="absolute -right-2 top-1 rounded-pill bg-surface2/90 border border-line/60 px-2 py-0.5 text-[10px] text-muted opacity-0 group-hover:opacity-100 transition">
    {label}
    </span>
    </NavLink>
)

export default function Sidebar(){
    return (
        <aside className="fixed left-6 top-6 bottom-6 z-50">
        <div className="h-full w-16 rounded-2xl bg-surface shadow-float border border-line/60 flex flex-col items-center gap-3 p-2">
        <div className="mt-1 mb-2 text-[10px] text-muted">nav</div>
        <Item to="/" icon={Gauge} label="Dash" />
        <Item to="/planning" icon={CalendarRange} label="Plan" />
        <Item to="/learning" icon={BookOpenCheck} label="Learning" />
        <Item to="/debug" icon={Bug} label="Debug" />
        <div className="mt-auto mb-1 w-8 h-px bg-line/70" />
        <Item to="/settings" icon={Settings} label="Settings" />
        </div>
        </aside>
    )
}

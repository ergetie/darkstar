import { Gauge, CalendarRange, BookOpenCheck, Bug, Settings, Bolt, Github } from 'lucide-react'
import { NavLink, Link, useLocation } from 'react-router-dom'

const Item = ({to, icon:Icon, label, onClick}:{to?:string; icon:any; label:string; onClick?:() => void}) => {
    const Component = to ? NavLink : 'button'
    const props = to ? { to } : { onClick }
    
    return (
        <Component
        {...props}
        className={({isActive}:any) =>
        `group relative flex items-center justify-center w-12 h-12 rounded-2xl border border-line/70
        bg-surface/80 hover:bg-surface2 transition ${isActive ? 'ring-2 ring-accent/50' : ''}`
        }
        title={label}
        >
        <Icon className="h-5 w-5 text-muted group-hover:text-text" />
        <span className="absolute -right-2 top-1 rounded-pill bg-surface2/90 border border-line/60 px-2 py-0.5 text-[10px] text-muted opacity-0 group-hover:opacity-100 transition">
        {label}
        </span>
        </Component>
    )
}

export default function Sidebar(){
    const { pathname } = useLocation()
    
    return (
        <aside className="fixed left-6 top-6 bottom-6 z-50">
        <div className="h-full w-16 rounded-2xl bg-surface shadow-float border border-line/60 flex flex-col items-center gap-3 p-2">
        {/* Logo - replaces "nav" text */}
        <Link to="/" className="mt-1 mb-2 flex items-center justify-center">
        <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-surface2 border border-line/60">
        <Bolt className="h-4 w-4 text-accent" />
        </span>
        </Link>
        
        {/* Navigation Items */}
        <Item to="/" icon={Gauge} label="Dash" />
        <Item to="/planning" icon={CalendarRange} label="Plan" />
        <Item to="/learning" icon={BookOpenCheck} label="Learning" />
        <Item to="/debug" icon={Bug} label="Debug" />
        
        <div className="mt-auto mb-1 w-8 h-px bg-line/70" />
        
        {/* Settings and GitHub */}
        <Item to="/settings" icon={Settings} label="Settings" />
        <Item 
        icon={Github} 
        label="Repo" 
        onClick={() => window.open('https://github.com/', '_blank')} 
        />
        </div>
        </aside>
    )
}

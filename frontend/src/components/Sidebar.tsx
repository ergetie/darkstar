import { useState, useEffect } from 'react'
import { Gauge, BookOpenCheck, Bug, Settings, Menu, X, FlaskConical, Bot, Cpu } from 'lucide-react'
import { NavLink, Link, useLocation } from 'react-router-dom'
import { DarkstarLogo } from './DarkstarLogo'
import { Api } from '../lib/api'
import pkg from '../../package.json'

const Item = ({ to, icon: Icon, label, onClick }: { to?: string; icon: any; label: string; onClick?: () => void }) => {
    const baseClass = "group relative flex items-center justify-center w-12 h-12 rounded-2xl border border-line/70 bg-surface/80 hover:bg-surface2 transition"
    const activeClass = "ring-2 ring-accent/50"

    const content = (
        <>
            <Icon className="h-5 w-5 text-muted group-hover:text-text" />
            <span className="absolute -right-2 top-1 rounded-pill bg-surface2/90 border border-line/60 px-2 py-0.5 text-[10px] text-muted opacity-0 group-hover:opacity-100 transition z-50 whitespace-nowrap">
                {label}
            </span>
        </>
    )

    if (to) {
        return (
            <NavLink
                to={to}
                className={({ isActive }) => `${baseClass} ${isActive ? activeClass : ''}`}
                title={label}
            >
                {content}
            </NavLink>
        )
    }

    return (
        <button
            onClick={onClick}
            className={baseClass}
            title={label}
        >
            {content}
        </button>
    )
}

export default function Sidebar() {
    const { pathname } = useLocation()
    const [mobileOpen, setMobileOpen] = useState(false)
    const [connected, setConnected] = useState<boolean | null>(null)

    useEffect(() => {
        const check = async () => {
            try {
                await Api.status()
                setConnected(true)
            } catch {
                setConnected(false)
            }
        }
        check()
        const i = setInterval(check, 30000)
        return () => clearInterval(i)
    }, [])

    const closeMobile = () => setMobileOpen(false)

    return (
        <>
            {/* Desktop sidebar */}
            <aside className="hidden lg:block fixed left-6 top-6 bottom-6 z-50">
                <div className="h-full w-16 rounded-2xl bg-surface shadow-float border border-line/60 flex flex-col items-center gap-3 p-2">
                    {/* Logo */}
                    <Link to="/" className="mt-1 mb-1 flex items-center justify-center group relative">
                        <span className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-surface2 border border-line/60 overflow-hidden">
                            <DarkstarLogo className="h-8 w-8 text-accent" />
                        </span>
                        <span className="absolute left-14 top-1/2 -translate-y-1/2 rounded-pill bg-surface2/90 border border-line/60 px-2 py-0.5 text-[10px] text-muted opacity-0 group-hover:opacity-100 transition whitespace-nowrap z-50 pointer-events-none">
                            darkstar v{pkg.version}
                        </span>
                    </Link>

                    {/* Navigation Items */}
                    <Item to="/" icon={Gauge} label="Dash" />
                    <Item to="/executor" icon={Cpu} label="Executor" />
                    <Item to="/aurora" icon={Bot} label="Aurora" />
                    <Item to="/lab" icon={FlaskConical} label="Lab" />
                    <Item to="/debug" icon={Bug} label="Debug" />

                    <div className="mt-auto w-8 h-px bg-line/70" />

                    {/* Version (Vertical) */}
                    <div className="py-2 flex flex-col items-center gap-2">
                        <div className={`h-1.5 w-1.5 rounded-full transition-all duration-500 ${connected === true ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]' :
                            connected === false ? 'bg-red-500' :
                                'bg-slate-700'
                            }`} title={connected === true ? 'System Online' : connected === false ? 'System Offline' : 'Connecting...'} />

                        <span className="text-[10px] text-muted/30 font-mono select-none tracking-widest whitespace-nowrap opacity-50 hover:opacity-100 transition" style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)' }}>
                            darkstar v{pkg.version}
                        </span>
                    </div>

                    {/* Settings */}
                    <Item to="/settings" icon={Settings} label="Settings" />
                </div>
            </aside>

            {/* Mobile top bar + hamburger */}
            <div className="lg:hidden fixed top-0 left-0 right-0 z-40 bg-surface/95 border-b border-line/60 flex items-center justify-between px-4 py-2">
                <button
                    type="button"
                    aria-label="Open navigation"
                    className="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-line/70 bg-surface2 text-muted hover:border-accent hover:text-accent"
                    onClick={() => setMobileOpen(true)}
                >
                    <Menu className="h-5 w-5" />
                </button>
                <div className="flex items-center gap-2 text-[11px] text-muted">
                    <DarkstarLogo className="h-5 w-5 text-accent" />
                    <span className="font-mono">v{pkg.version}</span>
                </div>
                <div className="w-10" />
            </div>

            {/* Mobile nav overlay */}
            {mobileOpen && (
                <div className="lg:hidden fixed inset-0 z-50 bg-[rgba(4,6,10,0.92)] backdrop-blur-sm">
                    <div className="flex items-center justify-between px-4 py-3 border-b border-line/60">
                        <div className="flex items-center gap-2 text-sm">
                            <span className="inline-flex h-9 w-9 items-center justify-center rounded-2xl bg-surface2 border border-line/60">
                                <DarkstarLogo className="h-5 w-5 text-accent" />
                            </span>
                            <span className="text-muted font-mono">darkstar v{pkg.version}</span>
                        </div>
                        <button
                            type="button"
                            aria-label="Close navigation"
                            className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-line/70 bg-surface text-muted hover:border-accent hover:text-accent"
                            onClick={closeMobile}
                        >
                            <X className="h-5 w-5" />
                        </button>
                    </div>

                    <div className="p-4 grid grid-cols-2 gap-3" onClick={closeMobile}>
                        <Link to="/" className={`flex flex-col items-center justify-center gap-2 p-4 rounded-2xl border ${pathname === '/' ? 'bg-surface2 border-accent/50 ring-1 ring-accent/50' : 'bg-surface/50 border-line/70'}`}>
                            <Gauge className={`h-6 w-6 ${pathname === '/' ? 'text-accent' : 'text-muted'}`} />
                            <span className="text-sm">Dash</span>
                        </Link>
                        <Link to="/executor" className={`flex flex-col items-center justify-center gap-2 p-4 rounded-2xl border ${pathname === '/executor' ? 'bg-surface2 border-accent/50 ring-1 ring-accent/50' : 'bg-surface/50 border-line/70'}`}>
                            <Cpu className={`h-6 w-6 ${pathname === '/executor' ? 'text-accent' : 'text-muted'}`} />
                            <span className="text-sm">Executor</span>
                        </Link>
                        <Link to="/aurora" className={`flex flex-col items-center justify-center gap-2 p-4 rounded-2xl border ${pathname === '/aurora' ? 'bg-surface2 border-accent/50 ring-1 ring-accent/50' : 'bg-surface/50 border-line/70'}`}>
                            <Bot className={`h-6 w-6 ${pathname === '/aurora' ? 'text-accent' : 'text-muted'}`} />
                            <span className="text-sm">Aurora</span>
                        </Link>
                        <Link to="/lab" className={`flex flex-col items-center justify-center gap-2 p-4 rounded-2xl border ${pathname === '/lab' ? 'bg-surface2 border-accent/50 ring-1 ring-accent/50' : 'bg-surface/50 border-line/70'}`}>
                            <FlaskConical className={`h-6 w-6 ${pathname === '/lab' ? 'text-accent' : 'text-muted'}`} />
                            <span className="text-sm">Lab</span>
                        </Link>
                        <Link to="/debug" className={`flex flex-col items-center justify-center gap-2 p-4 rounded-2xl border ${pathname === '/debug' ? 'bg-surface2 border-accent/50 ring-1 ring-accent/50' : 'bg-surface/50 border-line/70'}`}>
                            <Bug className={`h-6 w-6 ${pathname === '/debug' ? 'text-accent' : 'text-muted'}`} />
                            <span className="text-sm">Debug</span>
                        </Link>
                        <Link to="/settings" className={`flex flex-col items-center justify-center gap-2 p-4 rounded-2xl border ${pathname === '/settings' ? 'bg-surface2 border-accent/50 ring-1 ring-accent/50' : 'bg-surface/50 border-line/70'}`}>
                            <Settings className={`h-6 w-6 ${pathname === '/settings' ? 'text-accent' : 'text-muted'}`} />
                            <span className="text-sm">Settings</span>
                        </Link>
                    </div>
                </div>
            )}
        </>
    )
}

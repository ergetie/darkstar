import { useState } from 'react'
import { Gauge, CalendarRange, BookOpenCheck, Bug, Settings, Bolt, Menu, X, Activity, FlaskConical, Bot, Cpu } from 'lucide-react'
import { NavLink, Link, useLocation } from 'react-router-dom'

const Item = ({ to, icon: Icon, label, onClick }: { to?: string; icon: any; label: string; onClick?: () => void }) => {
    const Component = to ? NavLink : 'button'
    const props = to ? { to } : { onClick }

    return (
        <Component
            {...props}
            className={({ isActive }: any) =>
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

export default function Sidebar() {
    const { pathname } = useLocation()
    const [mobileOpen, setMobileOpen] = useState(false)

    const closeMobile = () => setMobileOpen(false)

    return (
        <>
            {/* Desktop sidebar */}
            <aside className="hidden lg:block fixed left-6 top-6 bottom-6 z-50">
                <div className="h-full w-16 rounded-2xl bg-surface shadow-float border border-line/60 flex flex-col items-center gap-3 p-2">
                    {/* Logo */}
                    <Link to="/" className="mt-1 mb-1 flex items-center justify-center">
                        <span className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-surface2 border border-line/60">
                            <Bolt className="h-5 w-5 text-accent" />
                        </span>
                    </Link>

                    {/* Navigation Items */}
                    <Item to="/" icon={Gauge} label="Dash" />
                    <Item to="/executor" icon={Cpu} label="Executor" />
                    <Item to="/aurora" icon={Bot} label="Aurora" />
                    <Item to="/lab" icon={FlaskConical} label="Lab" />
                    <Item to="/debug" icon={Bug} label="Debug" />

                    <div className="mt-auto mb-1 w-8 h-px bg-line/70" />

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
                    <Bolt className="h-4 w-4 text-accent" />
                    <span>Darkstar</span>
                </div>
                <div className="w-10" />
            </div>

            {/* Mobile nav overlay */}
            {mobileOpen && (
                <div className="lg:hidden fixed inset-0 z-50 bg-[rgba(4,6,10,0.92)] backdrop-blur-sm">
                    <div className="flex items-center justify-between px-4 py-3 border-b border-line/60">
                        <div className="flex items-center gap-2 text-sm">
                            <span className="inline-flex h-9 w-9 items-center justify-center rounded-2xl bg-surface2 border border-line/60">
                                <Bolt className="h-4 w-4 text-accent" />
                            </span>
                            <span className="text-muted">Darkstar</span>
                        </div>
                        <button
                            type="button"
                            aria-label="Close navigation"
                            className="inline-flex h-9 w-9 items-center justify-center rounded-xl border border-line/70 bg-surface text-muted hover:border-accent hover:text-accent"
                            onClick={closeMobile}
                        >
                            <X className="h-4 w-4" />
                        </button>
                    </div>
                    <nav className="px-4 py-4 space-y-2 text-sm">
                        <div className="text-[11px] uppercase tracking-wide text-muted mb-2">Main</div>
                        <button
                            type="button"
                            className={`flex w-full items-center justify-between rounded-xl px-3 py-2 text-left ${pathname === '/' ? 'bg-accent text-[#0F1216]' : 'bg-surface border border-line/60 text-muted'
                                }`}
                            onClick={closeMobile}
                        >
                            <span className="flex items-center gap-2">
                                <Gauge className="h-4 w-4" />
                                <NavLink to="/">Dashboard</NavLink>
                            </span>
                        </button>



                        <button
                            type="button"
                            className={`flex w-full items-center justify-between rounded-xl px-3 py-2 text-left ${pathname === '/executor' ? 'bg-accent text-[#0F1216]' : 'bg-surface border border-line/60 text-muted'
                                }`}
                            onClick={closeMobile}
                        >
                            <span className="flex items-center gap-2">
                                <Cpu className="h-4 w-4" />
                                <NavLink to="/executor">Executor</NavLink>
                            </span>
                        </button>

                        <button
                            type="button"
                            className={`flex w-full items-center justify-between rounded-xl px-3 py-2 text-left ${pathname === '/aurora' ? 'bg-accent text-[#0F1216]' : 'bg-surface border border-line/60 text-muted'
                                }`}
                            onClick={closeMobile}
                        >
                            <span className="flex items-center gap-2">
                                <Bot className="h-4 w-4" />
                                <NavLink to="/aurora">Aurora</NavLink>
                            </span>
                        </button>

                        <button
                            type="button"
                            className={`flex w-full items-center justify-between rounded-xl px-3 py-2 text-left ${pathname === '/lab' ? 'bg-accent text-[#0F1216]' : 'bg-surface border border-line/60 text-muted'
                                }`}
                            onClick={closeMobile}
                        >
                            <span className="flex items-center gap-2">
                                <FlaskConical className="h-4 w-4" />
                                <NavLink to="/lab">Lab</NavLink>
                            </span>
                        </button>

                        <button
                            type="button"
                            className={`flex w-full items-center justify-between rounded-xl px-3 py-2 text-left ${pathname === '/debug' ? 'bg-accent text-[#0F1216]' : 'bg-surface border border-line/60 text-muted'
                                }`}
                            onClick={closeMobile}
                        >
                            <span className="flex items-center gap-2">
                                <Bug className="h-4 w-4" />
                                <NavLink to="/debug">Debug</NavLink>
                            </span>
                        </button>

                        <div className="mt-4 text-[11px] uppercase tracking-wide text-muted mb-2">System</div>
                        <button
                            type="button"
                            className={`flex w-full items-center justify-between rounded-xl px-3 py-2 text-left ${pathname === '/settings' ? 'bg-accent text-[#0F1216]' : 'bg-surface border border-line/60 text-muted'
                                }`}
                            onClick={closeMobile}
                        >
                            <span className="flex items-center gap-2">
                                <Settings className="h-4 w-4" />
                                <NavLink to="/settings">Settings</NavLink>
                            </span>
                        </button>
                    </nav>
                </div>
            )}
        </>
    )
}

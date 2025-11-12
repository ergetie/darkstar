import { Bolt, Github } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'

export default function Header() {
    const { pathname } = useLocation()
    return (
        <header className="sticky top-0 z-40 backdrop-blur-sm bg-canvas/70 border-b border-line/60">
        <div className="mx-auto max-w-7xl px-6 py-4 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-3">
        <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-surface2 border border-line/60">
        <Bolt className="h-4 w-4 text-accent" />
        </span>
        <span className="tracking-tight font-semibold">DARKSTAR</span>
        <span className="text-muted text-xs ml-2">{pathname}</span>
        </Link>
        <a
        className="text-muted hover:text-text inline-flex items-center gap-2"
        href="https://github.com/"
        target="_blank" rel="noreferrer"
        >
        <Github className="h-4 w-4" />
        <span className="hidden sm:inline">Repo</span>
        </a>
        </div>
        </header>
    )
}

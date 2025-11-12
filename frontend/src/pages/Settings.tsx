import Card from '../components/Card'

const ascii = `     ____              _       _
|  _ \\  __ _ _ __ | | __ _| |_ ___  _ __
| | | |/ _\` | '_ \\| |/ _\` | __/ _ \\| '__|
| |_| | (_| | |_) | | (_| | || (_) | |
|____/ \\__,_| .__/|_|\\__,_|\\__\\___/|_|
|_|        DARKSTAR`

export default function Settings(){
    return (
        <main className="mx-auto max-w-7xl px-6 pb-24 pt-10 lg:pt-12">
        <div className="grid gap-6 md:grid-cols-2">
        <Card className="p-6">
        <div className="text-sm text-muted mb-3">Theme</div>
        <div className="grid gap-3">
        <div className="flex items-center gap-3">
        <div className="size-8 rounded-lg bg-accent border border-line/60" />
        <div className="text-sm">Accent: Yellow</div>
        </div>
        <div className="text-xs text-muted">Dark (never pure black), rounded, floating cards.</div>
        </div>
        </Card>

        <Card className="p-6">
        <div className="text-sm text-muted mb-3">ASCII Mark</div>
        <pre className="text-[12px] leading-4 text-accent/90">{ascii}</pre>
        </Card>
        </div>
        </main>
    )
}

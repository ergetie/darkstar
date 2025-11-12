import Card from '../components/Card'
export default function Debug(){
    return (
        <main className="mx-auto max-w-7xl px-6 pb-24 pt-10 lg:pt-12">
        <div className="grid gap-6 md:grid-cols-2">
        <Card className="p-6 min-h-[280px]">
        <div className="text-sm text-muted mb-3">Debug Metrics</div>
        <div>Metrics placeholder…</div>
        </Card>
        <Card className="p-6 min-h-[280px]">
        <div className="text-sm text-muted mb-3">Logs</div>
        <pre className="text-xs text-muted/90">[12:41] example log line…</pre>
        </Card>
        </div>
        </main>
    )
}

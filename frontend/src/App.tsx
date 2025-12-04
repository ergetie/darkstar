import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Dashboard from './pages/Dashboard'
import Planning from './pages/Planning'
import Learning from './pages/Learning'
import Debug from './pages/Debug'
import Settings from './pages/Settings'
import Forecasting from './pages/Forecasting'
import Lab from './pages/Lab'
import Aurora from './pages/Aurora'
import { Api } from './lib/api'

export default function App() {
    const [backendOffline, setBackendOffline] = useState(false)

    useEffect(() => {
        let cancelled = false
        let errorCount = 0

        const checkBackend = async () => {
            try {
                await Promise.all([Api.status(), Api.config()])
                if (cancelled) return
                errorCount = 0
                setBackendOffline(false)
            } catch {
                if (cancelled) return
                errorCount += 1
                if (errorCount >= 3) {
                    setBackendOffline(true)
                }
            }
        }

        checkBackend()
        const id = window.setInterval(checkBackend, 30000)

        return () => {
            cancelled = true
            window.clearInterval(id)
        }
    }, [])

    return (
        <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
            <Sidebar />
            <div className="lg:pl-[96px]">
                {backendOffline && (
                    <div className="bg-amber-900/80 border-b border-amber-500/60 text-amber-100 text-[11px] px-4 py-2 flex items-center justify-between">
                        <span>Backend appears offline or degraded. Some data may be stale or unavailable.</span>
                    </div>
                )}
                <Routes>
                    <Route path="/" element={<Dashboard />} />
                    <Route path="/planning" element={<Planning />} />
                    <Route path="/forecasting" element={<Forecasting />} />
                    <Route path="/aurora" element={<Aurora />} />
                    <Route path="/learning" element={<Learning />} />
                    <Route path="/debug" element={<Debug />} />
                    <Route path="/lab" element={<Lab />} />
                    <Route path="/settings" element={<Settings />} />
                </Routes>
            </div>
        </BrowserRouter>
    )
}

import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import ErrorBoundary from './components/ErrorBoundary'
import Dashboard from './pages/Dashboard'
import Debug from './pages/Debug'
import Settings from './pages/settings'
import Aurora from './pages/Aurora'
import Executor from './pages/Executor'
import DesignSystem from './pages/DesignSystem'
import PowerFlowLab from './pages/PowerFlowLab'
import ChartExamples from './pages/ChartExamples'
import { Api, HealthResponse } from './lib/api'
import { SystemAlert } from './components/SystemAlert'
import { ToastProvider } from './components/ui/Toast'

export default function App() {
    const [backendOffline, setBackendOffline] = useState(false)
    const [healthStatus, setHealthStatus] = useState<HealthResponse | null>(null)

    useEffect(() => {
        let cancelled = false
        let errorCount = 0

        const checkHealth = async () => {
            try {
                // Check both status and health
                const [, health] = await Promise.all([Api.status(), Api.health()])
                if (cancelled) return
                errorCount = 0
                setBackendOffline(false)
                setHealthStatus(health)
            } catch {
                if (cancelled) return
                errorCount += 1
                if (errorCount >= 3) {
                    setBackendOffline(true)
                    // Clear health status when backend is offline
                    setHealthStatus(null)
                }
            }
        }

        checkHealth()
        // Check every 60 seconds
        const id = window.setInterval(checkHealth, 60000)

        return () => {
            cancelled = true
            window.clearInterval(id)
        }
    }, [])

    // Help React Router find the base path when running under HA Ingress
    const getBasename = () => {
        const base = document.querySelector('base')
        const href = base?.getAttribute('href')
        if (href && href.startsWith('/')) {
            return href.replace(/\/$/, '') // Remove trailing slash
        }
        return '/'
    }

    return (
        <ErrorBoundary>
            <ToastProvider>
                <BrowserRouter
                    basename={getBasename()}
                    future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
                >
                    <Sidebar />
                    <div className="lg:pl-[96px]">
                        {/* Show health alerts if not fully healthy */}
                        {healthStatus && !healthStatus.healthy && <SystemAlert health={healthStatus} />}

                        {/* Show backend offline banner only if no health status available */}
                        {backendOffline && !healthStatus && (
                            <div className="bg-amber-900/80 border-b border-amber-500/60 text-amber-100 text-[11px] px-4 py-2 flex items-center justify-between">
                                <span>Backend appears offline or degraded. Some data may be stale or unavailable.</span>
                            </div>
                        )}
                        <Routes>
                            <Route path="/" element={<Dashboard />} />
                            <Route path="/executor" element={<Executor />} />
                            <Route path="/aurora" element={<Aurora />} />
                            <Route path="/debug" element={<Debug />} />
                            <Route path="/settings" element={<Settings />} />
                            <Route path="/design-system" element={<DesignSystem />} />
                            <Route path="/power-flow-lab" element={<PowerFlowLab />} />
                            <Route path="/chart-examples" element={<ChartExamples />} />
                        </Routes>
                    </div>
                </BrowserRouter>
            </ToastProvider>
        </ErrorBoundary>
    )
}

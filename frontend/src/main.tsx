import React from 'react'
import ReactDOM from 'react-dom/client'
import './index.css'

// Top-level error handler for module load failures
// (React ErrorBoundary can't catch these since they happen before React mounts)
const renderApp = async () => {
    try {
        const { default: App } = await import('./App')
        ReactDOM.createRoot(document.getElementById('root')!).render(
            <React.StrictMode>
                <App />
            </React.StrictMode>,
        )
    } catch (error) {
        console.error('Failed to load application:', error)
        const root = document.getElementById('root')
        if (root) {
            root.innerHTML = `
                <div style="
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    justify-content: center;
                    height: 100vh;
                    font-family: system-ui, sans-serif;
                    background: #0f1216;
                    color: #f0f0f0;
                    padding: 2rem;
                    text-align: center;
                ">
                    <h1 style="color: #ef4444; margin-bottom: 1rem;">⚠️ Application Load Error</h1>
                    <p style="color: #9ca3af; max-width: 500px; margin-bottom: 1.5rem;">
                        The dashboard failed to load. This is often caused by a build or cache issue.
                    </p>
                    <div style="
                        background: #1f2937;
                        padding: 1rem;
                        border-radius: 0.5rem;
                        font-family: monospace;
                        font-size: 0.875rem;
                        color: #fca5a5;
                        max-width: 600px;
                        overflow-x: auto;
                        margin-bottom: 1.5rem;
                    ">${error instanceof Error ? error.message : String(error)}</div>
                    <div style="display: flex; gap: 1rem;">
                        <button onclick="location.reload()" style="
                            padding: 0.75rem 1.5rem;
                            background: #3b82f6;
                            color: white;
                            border: none;
                            border-radius: 0.375rem;
                            cursor: pointer;
                            font-size: 0.875rem;
                        ">Reload Page</button>
                        <button onclick="navigator.clipboard.writeText('${error instanceof Error ? error.stack?.replace(/'/g, "\\'") : String(error)}')" style="
                            padding: 0.75rem 1.5rem;
                            background: #374151;
                            color: white;
                            border: none;
                            border-radius: 0.375rem;
                            cursor: pointer;
                            font-size: 0.875rem;
                        ">Copy Error</button>
                    </div>
                    <p style="color: #6b7280; font-size: 0.75rem; margin-top: 2rem;">
                        Try: <code style="background: #374151; padding: 0.25rem 0.5rem; border-radius: 0.25rem;">rm -rf node_modules/.vite && pnpm dev</code>
                    </p>
                </div>
            `
        }
    }
}

renderApp()

import { Component, ReactNode } from 'react'

interface Props {
    children: ReactNode
}

interface State {
    hasError: boolean
    error: Error | null
}

/**
 * Error boundary to catch runtime errors and display a friendly fallback UI.
 * Wraps the entire app to prevent blank screen crashes.
 */
export default class ErrorBoundary extends Component<Props, State> {
    constructor(props: Props) {
        super(props)
        this.state = { hasError: false, error: null }
    }

    static getDerivedStateFromError(error: Error): State {
        return { hasError: true, error }
    }

    componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
        console.error('[ErrorBoundary] Caught error:', error)
        console.error('[ErrorBoundary] Component stack:', errorInfo.componentStack)
    }

    handleReload = () => {
        window.location.reload()
    }

    render() {
        if (this.state.hasError) {
            return (
                <div className="min-h-screen bg-canvas flex items-center justify-center p-6">
                    <div className="max-w-md w-full bg-surface border border-line rounded-2xl p-8 shadow-float text-center">
                        <div className="h-16 w-16 mx-auto mb-4 rounded-full bg-red-500/20 border border-red-500/40 flex items-center justify-center">
                            <svg className="h-8 w-8 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    strokeWidth={2}
                                    d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                                />
                            </svg>
                        </div>
                        <h1 className="text-lg font-semibold text-text mb-2">Something went wrong</h1>
                        <p className="text-sm text-muted mb-4">The application encountered an unexpected error.</p>
                        {this.state.error && (
                            <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/30">
                                <code className="text-xs text-red-400 break-all">{this.state.error.message}</code>
                            </div>
                        )}
                        <button
                            onClick={this.handleReload}
                            className="px-6 py-2.5 rounded-full bg-accent text-canvas font-medium text-sm hover:bg-accent2 transition-colors"
                        >
                            Reload Page
                        </button>
                        <p className="mt-4 text-xs text-muted/60">
                            If this keeps happening, check the browser console for details.
                        </p>
                    </div>
                </div>
            )
        }

        return this.props.children
    }
}

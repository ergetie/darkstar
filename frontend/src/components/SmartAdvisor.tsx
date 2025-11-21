import { useState, useEffect } from 'react'
import { Sparkles, RefreshCw } from 'lucide-react'
import { Api } from '../lib/api'

export default function SmartAdvisor() {
  const [advice, setAdvice] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [disabled, setDisabled] = useState(false)

  const fetchAdvice = async () => {
    setLoading(true)
    setError(false)
    try {
      const res = await Api.getAdvice()
      if ((res as any).status === 'disabled') {
        setDisabled(true)
        setAdvice(null)
      } else {
        setDisabled(false)
        setAdvice(res.advice ?? null)
      }
    } catch (e) {
      console.error(e)
      setError(true)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchAdvice()
  }, [])

  if (error || disabled) return null

  return (
    <div className="card relative overflow-hidden border-l-4 border-l-accent p-4 bg-surface/50">
      <div className="flex items-start gap-3">
        <div className="mt-1 p-2 rounded-full bg-accent/10 text-accent">
          <Sparkles className="h-5 w-5" />
        </div>
        <div className="flex-1">
          <h3 className="text-sm font-medium text-muted uppercase tracking-wider mb-1">
            Aurora Advisor
          </h3>
          <div className="text-text leading-relaxed">
            {loading ? (
              <span className="animate-pulse">Analyzing schedule...</span>
            ) : advice ? (
              advice
            ) : (
              'No advice available.'
            )}
          </div>
        </div>
        <button
          onClick={fetchAdvice}
          disabled={loading}
          className="text-muted hover:text-text transition-colors p-1"
          title="Refresh Advice"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>
    </div>
  )
}

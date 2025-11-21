import { useState, useEffect } from 'react'
import { Sparkles, RefreshCw } from 'lucide-react'
import { Api } from '../lib/api'
import Card from './Card'

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
    <Card className="h-full p-4 md:p-5 flex flex-col">
      <div className="flex items-baseline justify-between mb-3">
        <div className="flex items-center gap-2 text-sm text-muted">
          <Sparkles className="h-4 w-4 text-accent" />
          <span>Aurora Advisor</span>
        </div>
        <button
          onClick={fetchAdvice}
          disabled={loading}
          className="text-[10px] text-muted hover:text-text transition-colors p-1"
          title="Refresh advice"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>
      <div className="text-[11px] text-text leading-relaxed">
        {loading ? (
          <span className="animate-pulse">Analyzing schedule...</span>
        ) : advice ? (
          advice
        ) : (
          'No advice available.'
        )}
      </div>
    </Card>
  )
}

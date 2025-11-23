import { useState, useEffect } from 'react'
import { Sparkles, RefreshCw } from 'lucide-react'
import { Api } from '../lib/api'
import Card from './Card'

export default function SmartAdvisor() {
  const [advice, setAdvice] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)
  const [llmEnabled, setLlmEnabled] = useState<boolean | null>(null)
  const [autoFetch, setAutoFetch] = useState<boolean>(true)

  const fetchAdvice = async () => {
    if (!llmEnabled) return
    setLoading(true)
    setError(false)
    try {
      const res = await Api.getAdvice()
      if ((res as any).status === 'disabled') {
        setLlmEnabled(false)
        setAdvice(null)
      } else {
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
    // Load advisor settings (enable_llm + auto_fetch) from config
    Api.config()
      .then((cfg) => {
        const advisor = cfg.advisor || {}
        const enabled = advisor.enable_llm !== false
        const auto = advisor.auto_fetch !== false
        setLlmEnabled(enabled)
        setAutoFetch(auto)
        if (enabled && auto) {
          fetchAdvice()
        }
      })
      .catch((err) => {
        console.error('Failed to load advisor config:', err)
        setLlmEnabled(false)
      })
  }, [])

  const canRequest = !!llmEnabled && !loading

  const toggleAutoFetch = async () => {
    const next = !autoFetch
    setAutoFetch(next)
    try {
      await Api.configSave({ advisor: { auto_fetch: next } })
      if (next && llmEnabled && !advice) {
        fetchAdvice()
      }
    } catch (err) {
      console.error('Failed to update advisor auto_fetch setting:', err)
    }
  }

  return (
    <Card className="h-full p-4 md:p-5 flex flex-col">
      <div className="flex items-baseline justify-between mb-3">
        <div className="flex items-center gap-2 text-sm text-muted">
          <Sparkles className="h-4 w-4 text-accent" />
          <span>Aurora Advisor</span>
        </div>
        <div className="flex items-center gap-2">
          {llmEnabled && (
            <button
              onClick={toggleAutoFetch}
              className={`rounded-pill px-2 py-1 text-[10px] font-medium transition ${
                autoFetch
                  ? 'bg-accent text-canvas border border-accent'
                  : 'bg-surface border border-line/60 text-muted hover:border-accent hover:text-accent'
              }`}
              title={
                autoFetch
                  ? 'Disable auto-fetch (advisor runs only on manual request)'
                  : 'Enable auto-fetch when the plan changes'
              }
            >
              ⏱
            </button>
          )}
          {llmEnabled !== null && (
            <button
              onClick={fetchAdvice}
              disabled={!canRequest}
              className="text-[10px] text-muted hover:text-text transition-colors p-1 disabled:opacity-40"
              title={llmEnabled ? 'Fetch latest advice' : 'Enable LLM advice in Settings'}
            >
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          )}
        </div>
      </div>
      <div className="text-[11px] text-text leading-relaxed">
        {llmEnabled === false && (
          <span className="text-muted">
            Smart Advisor is disabled. Enable LLM advice in Settings to get automated recommendations.
          </span>
        )}
        {llmEnabled === true && (
          <>
            {loading && <span className="animate-pulse">Analyzing schedule...</span>}
            {!loading && error && (
              <span className="text-red-400">Unable to fetch advice. Check AI settings or try again.</span>
            )}
            {!loading && !error && !advice && !autoFetch && (
              <span className="text-muted">Click the refresh icon to analyze your current schedule.</span>
            )}
            {!loading && !error && advice && <span>{advice}</span>}
          </>
        )}
        {llmEnabled === null && !loading && !error && (
          <span className="text-muted">Loading advisor settings…</span>
        )}
      </div>
    </Card>
  )
}

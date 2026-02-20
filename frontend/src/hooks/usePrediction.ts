import { useState } from 'react'
import { predictElectricity, predictWater, trainModels, getPredictionStatus } from '../api'
import type { PredictionResult } from '../api'

export function usePrediction() {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<PredictionResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<{
    electricity_model_ready: boolean
    water_model_ready: boolean
  } | null>(null)

  const predict = async (type: 'electricity' | 'water', duration_minutes: number) => {
    setLoading(true)
    setError(null)
    try {
      const res = type === 'electricity'
        ? await predictElectricity(duration_minutes)
        : await predictWater(duration_minutes)
      setResult(res)
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Prediction failed. Train model first.')
    } finally {
      setLoading(false)
    }
  }

  const train = async (pedestal_id?: number) => {
    setLoading(true)
    setError(null)
    try {
      await trainModels(pedestal_id)
      const s = await getPredictionStatus()
      setStatus(s)
    } catch {
      setError('Training failed.')
    } finally {
      setLoading(false)
    }
  }

  const checkStatus = async () => {
    try {
      const s = await getPredictionStatus()
      setStatus(s)
    } catch { /* ignore */ }
  }

  return { loading, result, error, status, predict, train, checkStatus }
}

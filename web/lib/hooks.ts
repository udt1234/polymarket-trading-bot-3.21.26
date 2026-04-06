import { useState, useEffect, useCallback, useRef } from "react"
import { apiFetch } from "./api"

export function useApi<T>(path: string | null, deps: any[] = [], refreshInterval?: number) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const refetch = useCallback(async () => {
    if (!path || path.includes("undefined") || path.includes("null")) {
      setLoading(false)
      return
    }
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setLoading(true)
    try {
      const res = await apiFetch<T>(path, { signal: controller.signal })
      if (!controller.signal.aborted) {
        setData(res)
        setError(null)
      }
    } catch (e: any) {
      if (e.name !== "AbortError" && !controller.signal.aborted) {
        setError(e.message)
      }
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false)
      }
    }
  }, [path])

  useEffect(() => {
    refetch()
    return () => abortRef.current?.abort()
  }, [refetch, ...deps])

  useEffect(() => {
    if (refreshInterval && refreshInterval > 0) {
      intervalRef.current = setInterval(refetch, refreshInterval)
      return () => {
        if (intervalRef.current) clearInterval(intervalRef.current)
      }
    }
  }, [refetch, refreshInterval])

  return { data, loading, error, refetch }
}

export function useMutation<T = any>(path: string, method: string = "POST") {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const mutate = useCallback(async (body?: any): Promise<T | null> => {
    setLoading(true)
    setError(null)
    try {
      const res = await apiFetch<T>(path, {
        method,
        body: body != null ? JSON.stringify(body) : undefined,
      })
      return res
    } catch (e: any) {
      setError(e.message)
      return null
    } finally {
      setLoading(false)
    }
  }, [path, method])

  return { mutate, loading, error }
}

export function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8010"

let _redirecting = false

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options?.headers,
    },
  })

  if (res.status === 401 && typeof window !== "undefined") {
    // Only redirect if not already redirecting
    if (!window.location.pathname.startsWith("/login") && !_redirecting) {
      _redirecting = true
      localStorage.removeItem("access_token")
      window.location.href = "/login"
    }
    throw new Error("Unauthorized")
  }

  if (!res.ok) {
    throw new Error(`API error: ${res.status}`)
  }

  return res.json()
}

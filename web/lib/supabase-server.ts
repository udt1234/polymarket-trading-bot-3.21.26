import { createClient, SupabaseClient } from "@supabase/supabase-js";

let client: SupabaseClient | null = null;

// Server-only Supabase client using the service key. Never import from
// client components (route handlers only).
export function supabaseServer(): SupabaseClient {
  if (!client) {
    const url = process.env.SUPABASE_URL;
    const key = process.env.SUPABASE_SERVICE_KEY;
    if (!url || !key) {
      throw new Error("SUPABASE_URL / SUPABASE_SERVICE_KEY not set");
    }
    client = createClient(url, key, {
      auth: { persistSession: false, autoRefreshToken: false },
      // Next.js App Router caches server-side fetch() by default, which froze
      // every Supabase query at the first response (the "engine stale" false
      // alarm). Force no-store on the client's own fetch so live data always
      // re-reads. `dynamic = "force-dynamic"` alone does NOT cover the
      // Supabase client's internal fetches.
      global: {
        fetch: (input: RequestInfo | URL, init?: RequestInit) =>
          fetch(input, { ...init, cache: "no-store" }),
      },
    });
  }
  return client;
}

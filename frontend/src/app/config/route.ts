import { NextRequest, NextResponse } from 'next/server'

/**
 * Runtime Configuration Endpoint
 *
 * This endpoint provides server-side environment variables to the client at runtime.
 * This solves the NEXT_PUBLIC_* limitation where variables are baked into the build.
 *
 * Environment Variables:
 * - API_URL: Where the browser/client should make API requests (public/external URL)
 * - INTERNAL_API_URL: Where Next.js server-side should proxy API requests (internal URL)
 *   Default: http://localhost:5055 (used by Next.js rewrites in next.config.ts)
 *
 * Why two different variables?
 * - API_URL: Used by browser clients when the API is on a different origin than the UI
 * - INTERNAL_API_URL: Used by Next.js rewrites for server-side proxying, typically http://localhost:5055
 *
 * Default behavior (no API_URL set):
 * Return an empty apiUrl so the browser uses same-origin `/api/*` requests.
 * Next.js rewrites those to INTERNAL_API_URL. This keeps Axios and relative
 * `fetch('/api/...')` calls on the same backend (critical for Docker publishes
 * where the UI is on :8503 and the API is on :5056).
 *
 * Set API_URL explicitly only when the browser must call the API on another host/port.
 */
export async function GET(_request: NextRequest) {
  const envApiUrl = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL

  if (envApiUrl) {
    return NextResponse.json({
      apiUrl: envApiUrl,
    })
  }

  console.log('[runtime-config] Using same-origin API via Next.js /api rewrite')
  return NextResponse.json({
    apiUrl: '',
  })
}

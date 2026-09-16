export const notice = 'Simulated feed — journeys are generated, no carrier is contacted.'
export type Finding = { family: string; severity: number; title: string; rule_id: string; evidence?: Record<string, unknown>[] }
export type Row = { id: string; number: string; valid: boolean; invalid_reason: string | null; status: string; eta: string | null; next_milestone: string | null; severity: number; band: string; exceptions: Finding[]; events?: Record<string, string>[]; explanation?: { text: string; action?: string; draft_message: string }; origin?: string; destination?: string }
export type Watchlist = { id: string; summary: { total: number; invalid: number; flagged: number }; containers: Row[] }
export function parseNumbers(text: string) { return text.split(/[\s,;]+/).map(x => x.trim()).filter(Boolean) }
export function label(text: string) { return text.toLowerCase().replaceAll('_', ' ') }
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 90000)
  try {
    const response = await fetch(`${import.meta.env.VITE_API_URL || ''}${path}`, { ...init, signal: controller.signal })
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new Error(typeof data.detail === 'string' ? data.detail : response.status === 429 ? 'Run limit reached. Please try again in an hour.' : 'The request could not be completed. Check your input and try again.')
    }
    return await response.json()
  } catch (error) {
    if (error instanceof TypeError || (error instanceof Error && error.name === 'AbortError')) throw new Error('The API is taking a moment to wake up. Please try again shortly.', { cause: error })
    throw error
  } finally { clearTimeout(timer) }
}

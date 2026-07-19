import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// Derives up-to-two-letter initials for Avatar fallbacks: first+last word
// initials for multi-word names, or just the first letter for a single word.
export function getInitials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return "?"
  if (parts.length === 1) return parts[0].charAt(0).toUpperCase()
  return (parts[0].charAt(0) + parts[parts.length - 1].charAt(0)).toUpperCase()
}

const relativeTimeFormatter = new Intl.RelativeTimeFormat("en-US", { numeric: "auto" })
const RELATIVE_TIME_UNITS: { unit: Intl.RelativeTimeFormatUnit; ms: number }[] = [
  { unit: "year", ms: 365 * 24 * 60 * 60 * 1000 },
  { unit: "month", ms: 30 * 24 * 60 * 60 * 1000 },
  { unit: "day", ms: 24 * 60 * 60 * 1000 },
  { unit: "hour", ms: 60 * 60 * 1000 },
  { unit: "minute", ms: 60 * 1000 },
]

// The backend serializes timestamps as naive UTC (no trailing Z/offset — Mongo returns
// tz-naive datetimes). `new Date()` would parse those as LOCAL time, skewing every relative/
// absolute display by the viewer's UTC offset. Treat a bare timestamp as UTC.
export function parseApiDate(iso: string): Date {
  return new Date(/([zZ]|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`)
}

// Coarse "2 minutes ago" / "in 3 days" via Intl.RelativeTimeFormat — no date library.
export function formatRelativeTime(iso: string): string {
  const diffMs = parseApiDate(iso).getTime() - Date.now()
  const absMs = Math.abs(diffMs)
  for (const { unit, ms } of RELATIVE_TIME_UNITS) {
    if (absMs >= ms) return relativeTimeFormatter.format(Math.round(diffMs / ms), unit)
  }
  return relativeTimeFormatter.format(Math.round(diffMs / 1000), "second")
}

"use client"

/**
 * Generic plain-English headline used above Whale Watching and Bracket
 * Analysis cards. Lines that start with "→" are formatted as actions (bold,
 * indented). Spec: WHALE_BRACKET_CARDS_SPEC.md.
 */
export function CardHeadline({
  emoji,
  title,
  lines,
}: {
  emoji: string
  title: string
  lines: string[]
}) {
  if (!lines || lines.length === 0) return null
  const summary = lines.filter((l) => !l.trim().startsWith("→"))
  const actions = lines.filter((l) => l.trim().startsWith("→"))
  return (
    <div className="mb-2 px-1">
      <p className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        <span className="mr-1">{emoji}</span>
        {title}
      </p>
      {summary.length > 0 && (
        <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
          {summary.join(" ")}
        </p>
      )}
      {actions.length > 0 && (
        <ul className="mt-1 space-y-0.5">
          {actions.map((line, i) => (
            <li key={i} className="text-xs font-medium text-foreground leading-relaxed">
              {line.replace(/^→\s*/, "→ ")}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

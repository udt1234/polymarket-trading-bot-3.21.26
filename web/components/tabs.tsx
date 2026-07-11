"use client";

export interface TabDef {
  id: string;
  label: string;
}

export default function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: TabDef[];
  active: string;
  onChange: (id: string) => void;
}) {
  return (
    <nav className="flex flex-wrap gap-1 border-b border-term-border">
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={`relative px-3 py-2 text-sm uppercase tracking-wider transition-colors ${
            active === t.id
              ? "text-term-gold"
              : "text-term-muted hover:text-term-text"
          }`}
        >
          {t.label}
          {active === t.id && (
            <span className="absolute inset-x-2 -bottom-px h-0.5 rounded bg-term-gold" />
          )}
        </button>
      ))}
    </nav>
  );
}

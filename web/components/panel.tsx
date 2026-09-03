export default function Panel({
  title,
  right,
  children,
}: {
  title: string;
  right?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded border border-term-border bg-term-panel">
      <header className="flex items-center justify-between border-b border-term-border px-3 py-2">
        <h2 className="text-xs uppercase tracking-widest text-term-muted">
          {title}
        </h2>
        {right}
      </header>
      <div className="overflow-x-auto">{children}</div>
    </section>
  );
}

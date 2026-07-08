import { CircuitBreaker } from "@/lib/types";

export default function BreakerBanner({
  breaker,
}: {
  breaker: CircuitBreaker | null;
}) {
  const until = breaker?.cooldown_until;
  const tripped = !!until && new Date(until).getTime() > Date.now();
  if (!tripped) return null;
  return (
    <div className="rounded border border-term-red bg-term-red/15 px-3 py-2 text-term-red">
      CIRCUIT BREAKER TRIPPED: trading paused until{" "}
      {new Date(until!).toLocaleString()} ({breaker?.consecutive_losses ?? "?"}{" "}
      consecutive losses, {breaker?.trips ?? "?"} trips)
    </div>
  );
}

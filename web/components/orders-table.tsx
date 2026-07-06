import { Module, Order } from "@/lib/types";
import { fmtCents, fmtSize, fmtTime } from "@/lib/format";

export default function OrdersTable({
  orders,
  modules,
}: {
  orders: Order[];
  modules: Module[];
}) {
  if (orders.length === 0) {
    return <p className="px-3 py-4 text-term-muted">no resting orders</p>;
  }
  return (
    <table className="w-full text-left text-xs">
      <thead>
        <tr className="text-term-muted">
          <th className="px-3 py-1.5 font-normal">module</th>
          <th className="px-3 py-1.5 font-normal">side</th>
          <th className="px-3 py-1.5 font-normal">bracket</th>
          <th className="px-3 py-1.5 text-right font-normal">price</th>
          <th className="px-3 py-1.5 text-right font-normal">size</th>
          <th className="px-3 py-1.5 text-right font-normal">filled</th>
          <th className="px-3 py-1.5 font-normal">status</th>
          <th className="px-3 py-1.5 font-normal">executor</th>
          <th className="px-3 py-1.5 font-normal">created</th>
        </tr>
      </thead>
      <tbody>
        {orders.map((o) => (
          <tr key={o.id} className="border-t border-term-border/60">
            <td className="px-3 py-1.5">
              {modules.find((m) => m.id === o.module_id)?.name ?? "?"}
            </td>
            <td
              className={`px-3 py-1.5 ${
                o.side === "BUY" ? "text-term-green" : "text-term-red"
              }`}
            >
              {o.side}
            </td>
            <td className="px-3 py-1.5 text-term-accent">{o.bracket ?? "-"}</td>
            <td className="px-3 py-1.5 text-right">{fmtCents(o.price)}</td>
            <td className="px-3 py-1.5 text-right">{fmtSize(o.size)}</td>
            <td className="px-3 py-1.5 text-right">
              {fmtSize(o.size_filled ?? 0)}
            </td>
            <td className="px-3 py-1.5">
              <span
                className={
                  o.status === "partially_filled"
                    ? "text-term-amber"
                    : "text-term-accent"
                }
              >
                {o.status}
              </span>
            </td>
            <td className="px-3 py-1.5 text-term-muted">{o.executor}</td>
            <td className="px-3 py-1.5 text-term-muted">
              {fmtTime(o.created_at)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

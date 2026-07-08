export interface Module {
  id: string;
  name: string;
  strategy: string;
  budget: number;
  status: string; // active | paper | inactive
  inactive_reason: string | null;
  updated_at: string;
}

export interface Position {
  id: string;
  module_id: string;
  market_id: string | null;
  bracket: string | null;
  side: string;
  size: number;
  avg_price: number;
  exit_price: number | null;
  realized_pnl: number;
  unrealized_pnl: number;
  status: string; // open | closing | closed
  opened_at: string;
  closed_at: string | null;
}

export interface Order {
  id: string;
  module_id: string;
  market_id: string | null;
  bracket: string | null;
  side: string;
  size: number;
  size_filled: number | null;
  price: number;
  status: string;
  executor: string;
  created_at: string;
}

export interface Signal {
  id: string;
  module_id: string;
  bracket: string | null;
  side: string;
  edge: number | null;
  model_prob: number | null;
  market_price: number | null;
  approved: boolean;
  rejection_reason: string | null;
  created_at: string;
}

export interface CircuitBreaker {
  trips?: number;
  cooldown_until?: string;
  consecutive_losses?: number;
}

export interface TerminalData {
  modules: Module[];
  positions: Position[];
  closed_positions: Position[];
  orders: Order[];
  signals: Signal[];
  circuit_breaker: CircuitBreaker | null;
  last_cycle_at: string | null;
  last_cycle_message: string | null;
  trades_by_module: Record<string, number>;
  fetched_at: string;
}

export interface SnapshotPoint {
  snapshot_hour: string;
  price: number;
}

export interface SnapshotData {
  brackets: string[];
  bracket: string | null;
  points: SnapshotPoint[];
}

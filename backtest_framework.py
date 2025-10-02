
import argparse
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple
import pandas as pd
import numpy as np
import math
import sys
import os

# ============ Data Loading ============
def load_data(csv_path: str, symbol: Optional[str] = None) -> pd.DataFrame:
    """
    Expects columns: date, open, high, low, close, volume, money, open_interest, symbol
    Returns a DataFrame indexed by datetime with float columns.
    """
    df = pd.read_csv(csv_path)
    # Try to be robust to column case/whitespace
    df.columns = [c.strip().lower() for c in df.columns]
    expected = {"date","open","high","low","close","volume","money","open_interest","symbol"}
    missing = expected - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in CSV: {missing}")
    if symbol is not None:
        df = df[df["symbol"] == symbol]
        if df.empty:
            raise ValueError(f"No rows for symbol={symbol}")
    # parse datetime
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")
    # Ensure dtype
    float_cols = ["open","high","low","close","volume","money","open_interest"]
    df[float_cols] = df[float_cols].astype(float)
    return df

# ============ Order & Execution Models ============
@dataclass
class Order:
    side: str          # "BUY" or "SELL"
    size: int          # contracts (positive integer)
    reason: str = ""   # optional reason tag
    # market order executed next bar open with slippage

@dataclass
class Fill:
    dt: pd.Timestamp
    side: str
    size: int
    price: float
    fee: float
    slippage: float

@dataclass
class Position:
    contracts: int = 0   # +long, -short
    avg_price: float = 0 # VWAP entry price in instrument price units

    def update_on_fill(self, side: str, size: int, price: float):
        if side not in ("BUY","SELL"):
            raise ValueError("side must be BUY/SELL")
        signed = size if side == "BUY" else -size

        if self.contracts == 0:
            self.contracts = signed
            self.avg_price = price if self.contracts != 0 else 0.0
            return

        new_contracts = self.contracts + signed

        # Adding to an existing position on the same side
        if (self.contracts > 0 and signed > 0) or (self.contracts < 0 and signed < 0):
            total = abs(self.contracts) + size
            self.avg_price = (abs(self.contracts) * self.avg_price + size * price) / total
            self.contracts = new_contracts
            return

        # Reducing but still keeping the same side exposure
        if np.sign(self.contracts) == np.sign(new_contracts) and new_contracts != 0:
            self.contracts = new_contracts
            return

        # Fully flat
        if new_contracts == 0:
            self.contracts = 0
            self.avg_price = 0.0
            return

        # Flipped to the opposite side
        self.contracts = new_contracts
        self.avg_price = price

# ============ Strategy Base ============
class Strategy:
    def __init__(self, params: Optional[Dict[str,Any]]=None):
        self.params = params or {}

    def init(self, data: pd.DataFrame):
        """Called once. You may precompute indicators and store them on self."""
        pass

    def on_bar(self, i: int, row: pd.Series, pos: Position) -> List[Order]:
        """Return a list of market orders to be executed on next bar open.
        i: integer bar index (0..n-1), row: current bar Series, pos: current position snapshot."""
        return []

# ============ Example Strategy ============
class SMAWithOIStrategy(Strategy):
    """Long when close > SMA(n) and OI rising, flat otherwise. Symmetric short optional."""
    def init(self, data: pd.DataFrame):
        n = int(self.params.get("n", 20))
        self.allow_short = bool(self.params.get("allow_short", False))
        self.contracts = int(self.params.get("contracts", 1))
        self.sma = data["close"].rolling(n, min_periods=1).mean()
        self.oi_chg = data["open_interest"].diff()

    def on_bar(self, i: int, row: pd.Series, pos: Position) -> List[Order]:
        orders: List[Order] = []
        close = row["close"]
        sma = self.sma.iat[i]
        oi_up = (self.oi_chg.iat[i] or 0) > 0
        # Signals
        long_signal = close > sma and oi_up
        short_signal = self.allow_short and (close < sma) and oi_up

        # Position logic: simple target-position style
        target = 0
        if long_signal:
            target = self.contracts
        elif short_signal:
            target = -self.contracts
        else:
            target = 0

        delta = target - pos.contracts
        if delta > 0:
            orders.append(Order(side="BUY", size=delta, reason="target_up"))
        elif delta < 0:
            orders.append(Order(side="SELL", size=abs(delta), reason="target_down"))
        return orders

# ============ Backtester ============
class Backtester:
    def __init__(
        self,
        data: pd.DataFrame,
        strategy: Strategy,
        contract_multiplier: float = 300.0,
        fee_rate: float = 2e-4,          # commission as fraction of notional per side
        tick_size: float = 0.2,
        slippage_ticks: int = 1,
        initial_cash: float = 1_000_000.0,
    ):
        self.data = data
        self.strategy = strategy
        self.mult = contract_multiplier
        self.fee_rate = fee_rate
        self.tick_size = tick_size
        self.slippage_ticks = slippage_ticks
        self.initial_cash = initial_cash

        self.position = Position()
        self.cash = initial_cash
        self.equity_curve: List[Tuple[pd.Timestamp, float]] = []
        self.fills: List[Fill] = []
        self.orders_pending: List[Order] = []  # orders created at bar t to be executed at t+1 open (market)
        self.trade_log: List[Dict[str, Any]] = []
        self.open_trade: Optional[Dict[str, Any]] = None
        self.ts_to_idx: Dict[pd.Timestamp, int] = {}

    def _exec_orders(self, dt_next: pd.Timestamp, open_next: float):
        """Execute all pending market orders at next bar open with slippage."""
        executed: List[Fill] = []
        for od in self.orders_pending:
            slip = self.slippage_ticks * self.tick_size
            # Buy pays up, sell receives down (adverse selection)
            px = open_next + (slip if od.side=="BUY" else -slip)
            notional = px * self.mult * od.size
            fee = abs(notional) * self.fee_rate
            executed.append(Fill(dt=dt_next, side=od.side, size=od.size, price=px, fee=fee, slippage=slip))

            pos_before = self.position.contracts
            avg_price = self.position.avg_price
            realized = 0.0
            if od.side == "SELL" and pos_before > 0:
                close_qty = min(pos_before, od.size)
                realized = (px - avg_price) * self.mult * close_qty
            elif od.side == "BUY" and pos_before < 0:
                close_qty = min(-pos_before, od.size)
                realized = (avg_price - px) * self.mult * close_qty

            self.position.update_on_fill(od.side, od.size, px)
            self.cash += realized
            self.cash -= fee  # commission is cash cost

            pos_after = self.position.contracts
            direction_after = "LONG" if pos_after > 0 else "SHORT" if pos_after < 0 else None

            trade = self.open_trade
            if trade is None and direction_after is not None:
                self.open_trade = {
                    "direction": direction_after,
                    "entry_time": dt_next,
                    "entry_idx": self.ts_to_idx.get(dt_next),
                    "entry_price": self.position.avg_price,
                    "max_size": abs(pos_after),
                    "fees": fee,
                    "gross_pnl": realized,
                }
                continue

            if trade is not None:
                trade["fees"] += fee
                trade["gross_pnl"] += realized
                if pos_after != 0 and direction_after == trade["direction"]:
                    trade["entry_price"] = self.position.avg_price
                    trade["max_size"] = max(trade["max_size"], abs(pos_after))

                should_close = pos_after == 0 or (trade["direction"] == "LONG" and pos_after < 0) or (trade["direction"] == "SHORT" and pos_after > 0)
                if should_close:
                    exit_idx = self.ts_to_idx.get(dt_next)
                    if exit_idx is not None and trade["entry_idx"] is not None:
                        bars_held = max(0, exit_idx - trade["entry_idx"])
                    else:
                        bars_held = 0
                    holding_minutes = (dt_next - trade["entry_time"]).total_seconds() / 60.0 if trade["entry_time"] is not None else None
                    net_pnl = trade["gross_pnl"] - trade["fees"]
                    trade_record = {
                        "direction": trade["direction"],
                        "entry_time": trade["entry_time"],
                        "exit_time": dt_next,
                        "entry_price": trade["entry_price"],
                        "exit_price": px,
                        "contracts": trade["max_size"],
                        "gross_pnl": trade["gross_pnl"],
                        "fees": trade["fees"],
                        "net_pnl": net_pnl,
                        "bars_held": bars_held,
                        "holding_minutes": holding_minutes,
                    }
                    self.trade_log.append(trade_record)
                    self.open_trade = None

                    if pos_after != 0:
                        self.open_trade = {
                            "direction": "LONG" if pos_after > 0 else "SHORT",
                            "entry_time": dt_next,
                            "entry_idx": self.ts_to_idx.get(dt_next),
                            "entry_price": self.position.avg_price,
                            "max_size": abs(pos_after),
                            "fees": 0.0,
                            "gross_pnl": 0.0,
                        }

        self.orders_pending.clear()
        self.fills.extend(executed)
    def _mark_to_market(self, dt: pd.Timestamp, last_price: float):
        """Revalue equity based on current price and avg entry price of open contracts."""
        pos = self.position.contracts
        # Unrealized PnL = (CurrentPrice - AvgPrice) * mult * contracts (sign-aware)
        unrealized = (last_price - self.position.avg_price) * self.mult * pos if pos != 0 else 0.0
        equity = self.cash + unrealized
        self.equity_curve.append((dt, equity))

    def run(self) -> pd.DataFrame:
        df = self.data
        self.position = Position()
        self.cash = self.initial_cash
        self.equity_curve = []
        self.fills = []
        self.orders_pending = []
        self.trade_log = []
        self.open_trade = None
        self.ts_to_idx = {ts: idx for idx, ts in enumerate(df.index)}
        self.strategy.init(df)

        # iterate bars; orders generated on bar i execute on i+1 open
        for i in range(len(df)-1):
            idx = df.index[i]
            row = df.iloc[i]
            next_idx = df.index[i+1]
            next_open = df["open"].iat[i+1]

            # Strategy decides orders using info up to current bar
            new_orders = self.strategy.on_bar(i, row, Position(contracts=self.position.contracts, avg_price=self.position.avg_price))
            self.orders_pending.extend(new_orders)

            # Execute at next bar open
            if self.orders_pending:
                self._exec_orders(next_idx, next_open)

            # Mark to market at current close (or next open? We'll use current close for smoother curve)
            self._mark_to_market(idx, row["close"])

        # Final MTM at last bar close
        last_idx = df.index[-1]
        last_close = df["close"].iat[-1]
        self._mark_to_market(last_idx, last_close)

        eq_df = pd.DataFrame(self.equity_curve, columns=["datetime","equity"]).set_index("datetime")
        return eq_df

    def summary(self) -> Dict[str, Any]:
        eq = pd.DataFrame(self.equity_curve, columns=["datetime","equity"]).set_index("datetime")
        if eq.empty:
            return {}
        ret = eq["equity"].pct_change().dropna()
        total_return = (eq["equity"].iloc[-1] / eq["equity"].iloc[0]) - 1.0
        vol = ret.std() * math.sqrt(252*4*60)  # rough: 4 hours * 60 minutes of "active" mins
        sharpe = ret.mean()/ret.std()*math.sqrt(252*4*60) if ret.std()>0 else np.nan
        max_dd = ((eq["equity"]/eq["equity"].cummax())-1.0).min()

        summary = {
            "start": eq.index[0],
            "end": eq.index[-1],
            "initial_cash": self.initial_cash,
            "final_equity": float(eq["equity"].iloc[-1]),
            "total_return": float(total_return),
            "volatility_ann": float(vol) if not np.isnan(vol) else None,
            "sharpe_like": float(sharpe) if not np.isnan(sharpe) else None,
            "max_drawdown": float(max_dd),
            "trades": len(self.fills),
        }

        total_fees = sum(fill.fee for fill in self.fills)
        summary["total_fees"] = float(total_fees)

        trades_df = pd.DataFrame(self.trade_log)
        if not trades_df.empty:
            net = trades_df["net_pnl"]
            summary["win_rate"] = float((net > 0).mean())
            summary["max_trade_gain"] = float(net.max())
            summary["max_trade_loss"] = float(net.min())
            summary["avg_fee_per_trade"] = float(trades_df["fees"].mean())
            summary["total_gross_pnl"] = float(trades_df["gross_pnl"].sum())
            summary["total_net_pnl"] = float(net.sum())
            summary["avg_bars_held"] = float(trades_df["bars_held"].mean())
            summary["max_bars_held"] = int(trades_df["bars_held"].max())

            if "holding_minutes" in trades_df.columns:
                holding = trades_df["holding_minutes"].dropna()
                summary["avg_holding_minutes"] = float(holding.mean()) if not holding.empty else None
                summary["max_holding_minutes"] = float(holding.max()) if not holding.empty else None
        else:
            summary["win_rate"] = None
            summary["max_trade_gain"] = None
            summary["max_trade_loss"] = None
            summary["avg_fee_per_trade"] = None
            summary["total_gross_pnl"] = 0.0
            summary["total_net_pnl"] = 0.0
            summary["avg_bars_held"] = None
            summary["max_bars_held"] = None
            summary["avg_holding_minutes"] = None
            summary["max_holding_minutes"] = None

        return summary

    def trades(self) -> pd.DataFrame:
        """Return the trade log as a DataFrame."""
        return pd.DataFrame(self.trade_log)

def main():
    parser = argparse.ArgumentParser(description="Simple futures backtester for Chinese minute bars.")
    parser.add_argument("--csv", required=True, help="Path to CSV with columns: date,open,high,low,close,volume,money,open_interest,symbol")
    parser.add_argument("--symbol", default=None, help="Filter by symbol, e.g., IF1005")
    parser.add_argument("--multiplier", type=float, default=300.0, help="Contract multiplier, e.g., IF=300")
    parser.add_argument("--fee_rate", type=float, default=2e-4, help="Commission per side as fraction of notional")
    parser.add_argument("--tick_size", type=float, default=0.2, help="Tick size")
    parser.add_argument("--slippage_ticks", type=int, default=1, help="Slippage in ticks for market orders")
    parser.add_argument("--contracts", type=int, default=1, help="Target contracts for example strategy")
    parser.add_argument("--sma_n", type=int, default=20, help="SMA window for example strategy")
    parser.add_argument("--allow_short", action="store_true", help="Enable shorting in example strategy")
    args = parser.parse_args()

    data = load_data(args.csv, symbol=args.symbol)
    strat = SMAWithOIStrategy(params={"n": args.sma_n, "contracts": args.contracts, "allow_short": args.allow_short})
    bt = Backtester(
        data,
        strategy=strat,
        contract_multiplier=args.multiplier,
        fee_rate=args.fee_rate,
        tick_size=args.tick_size,
        slippage_ticks=args.slippage_ticks,
    )
    eq = bt.run()
    summ = bt.summary()

    # Print summary
    print("=== Backtest Summary ===")
    for k,v in summ.items():
        print(f"{k}: {v}")
    # Save equity curve
    out_path = os.path.splitext(args.csv)[0] + "_equity.csv"
    eq.to_csv(out_path)
    print(f"Equity curve saved to: {out_path}")

if __name__ == "__main__":
    # Allow running as script
    main()

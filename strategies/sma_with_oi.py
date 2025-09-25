from typing import Optional, Dict, Any, List
import pandas as pd
from dataclasses import dataclass

# Import Strategy and Position from backtest_framework
from ..backtest_framework import Strategy, Position, Order

class SMAWithOIStrategy(Strategy):
    """Long when close > SMA(n) and OI rising, flat otherwise. Symmetric short optional."""
    
    def __init__(self, params: Optional[Dict[str,Any]]=None):
        super().__init__(params)
        # Set default parameters
        self.n = int(self.params.get("n", 20))
        self.allow_short = bool(self.params.get("allow_short", False))
        self.contracts = int(self.params.get("contracts", 1))
        
    def init(self, data: pd.DataFrame):
        """Initialize strategy parameters and precompute indicators."""
        # Calculate SMA and OI change indicators
        self.sma = data["close"].rolling(self.n, min_periods=1).mean()
        self.oi_chg = data["open_interest"].diff()
        
    def on_bar(self, i: int, row: pd.Series, pos: Position) -> List[Order]:
        """Generate trading signals based on SMA and open interest changes."""
        orders: List[Order] = []
        
        # Get current values
        close = row["close"]
        sma = self.sma.iat[i]
        oi_up = (self.oi_chg.iat[i] or 0) > 0
        
        # Generate signals
        long_signal = close > sma and oi_up
        short_signal = self.allow_short and (close < sma) and oi_up
        
        # Determine target position based on signals
        target = 0
        if long_signal:
            target = self.contracts
        elif short_signal:
            target = -self.contracts
        else:
            target = 0
        
        # Calculate position delta and generate orders
        delta = target - pos.contracts
        if delta > 0:
            orders.append(Order(side="BUY", size=delta, reason="target_up"))
        elif delta < 0:
            orders.append(Order(side="SELL", size=abs(delta), reason="target_down"))
        
        return orders
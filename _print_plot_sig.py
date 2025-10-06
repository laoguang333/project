import inspect
from backtesting.backtesting import Backtest

print(inspect.signature(Backtest.plot))
print(Backtest.plot.__doc__)

from stealth_monitor.config import INSTRUMENTS, TIMEFRAMES
from stealth_monitor.data_sources import fetch_data

stock = INSTRUMENTS[2]
for tf in TIMEFRAMES:
    if tf.category == "minute":
        df = fetch_data(stock, tf, limit=5)
        print(tf.key, df.tail())

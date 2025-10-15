# 在所有导入之前设置DPI感知和环境变量
import os
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
os.environ["QT_LOGGING_RULES"] = "qt.qpa.window=false"

# 设置DPI感知以解决Qt警告
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except:
    pass

from .app import run


if __name__ == "__main__":
    run()


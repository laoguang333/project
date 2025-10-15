"""
单实例检查模块
提供跨平台的单实例检查功能，当前实现基于Windows互斥体
"""

import sys
import os


class SingleInstanceChecker:
    """
    单实例检查器
    使用Windows互斥体实现，确保同一时间只能运行一个实例
    """
    
    def __init__(self, app_name="StealthMonitor"):
        """
        初始化单实例检查器
        
        Args:
            app_name (str): 应用程序名称，用于创建唯一的互斥体名称
        """
        self.app_name = app_name
        self.mutex_name = f"Global\\{app_name}_Mutex"
        self.mutex_handle = None
        
    def is_already_running(self):
        """
        检查是否已有实例在运行
        
        Returns:
            bool: 如果已有实例在运行返回True，否则返回False
        """
        # 仅在Windows平台上使用互斥体检查
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes
                
                # Windows API常量
                ERROR_ALREADY_EXISTS = 183
                
                # 创建互斥体
                kernel32 = ctypes.windll.kernel32
                kernel32.CreateMutexW.argtypes = [wintypes.LPCVOID, wintypes.BOOL, wintypes.LPCWSTR]
                kernel32.CreateMutexW.restype = wintypes.HANDLE
                
                # 创建命名互斥体
                self.mutex_handle = kernel32.CreateMutexW(None, False, self.mutex_name)
                
                # 检查是否已存在
                last_error = kernel32.GetLastError()
                if last_error == ERROR_ALREADY_EXISTS:
                    return True
                return False
            except Exception as e:
                # 如果出现异常，默认允许运行（避免阻止程序启动）
                print(f"单实例检查出现异常: {e}")
                return False
        else:
            # 非Windows平台暂不实现互斥体检查
            return False
    
    def release(self):
        """
        释放资源
        """
        if self.mutex_handle and sys.platform == "win32":
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                kernel32.CloseHandle(self.mutex_handle)
                self.mutex_handle = None
            except Exception:
                pass


# 创建全局单实例检查器实例
_single_instance_checker = SingleInstanceChecker()


def check_single_instance():
    """
    检查是否已有实例在运行，如果有则退出程序
    
    Returns:
        bool: 如果程序可以继续运行返回True，如果已有实例在运行则退出程序返回False
    """
    if _single_instance_checker.is_already_running():
        print(f"{_single_instance_checker.app_name} 已在运行中，请勿重复启动。")
        sys.exit(0)
    return True


def release_single_instance():
    """
    释放单实例检查器资源
    """
    _single_instance_checker.release()
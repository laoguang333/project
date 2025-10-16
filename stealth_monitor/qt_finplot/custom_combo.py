"""
自定义ComboBox控件，支持滚轮环形滚动功能
"""

from PyQt6 import QtCore, QtGui, QtWidgets


class CircularComboBox(QtWidgets.QComboBox):
    """支持滚轮环形滚动的ComboBox"""
    
    def __init__(self, parent=None):
        """
        初始化环形ComboBox
        
        Args:
            parent: 父控件
        """
        super().__init__(parent)
        # 设置焦点策略，确保能接收滚轮事件
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        # 启用滚轮事件
        self.setMouseTracking(True)
        
    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        """
        重写滚轮事件，实现环形滚动功能
        
        Args:
            event: 滚轮事件
        """
        # 检查鼠标是否在控件上
        if not self.underMouse() and event.buttons() == QtCore.Qt.MouseButton.NoButton:
            # 如果鼠标不在控件上且没有按下鼠标按钮，不处理滚轮事件
            # 这样可以避免在用户滚动页面时意外改变选择
            event.ignore()
            return
            
        # 获取当前索引和项目总数
        current_index = self.currentIndex()
        count = self.count()
        
        # 如果没有项目或只有一个项目，使用默认行为
        if count <= 1:
            super().wheelEvent(event)
            return
            
        # 计算滚动方向
        # angleDelta().y() > 0 表示向上滚动
        # angleDelta().y() < 0 表示向下滚动
        delta = event.angleDelta().y()
        
        if delta > 0:
            # 向上滚动
            new_index = current_index - 1
            if new_index < 0:
                # 如果到达顶部，循环到最后一项
                new_index = count - 1
        else:
            # 向下滚动
            new_index = current_index + 1
            if new_index >= count:
                # 如果到达底部，循环到第一项
                new_index = 0
                
        # 设置新索引
        self.setCurrentIndex(new_index)
        
        # 接受事件，防止传递给父控件
        event.accept()
        
    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        """
        重写键盘事件，支持键盘导航的环形滚动
        
        Args:
            event: 键盘事件
        """
        # 获取当前索引和项目总数
        current_index = self.currentIndex()
        count = self.count()
        
        # 如果没有项目或只有一个项目，使用默认行为
        if count <= 1:
            super().keyPressEvent(event)
            return
            
        # 处理向上和向下键
        if event.key() == QtCore.Qt.Key.Key_Up:
            # 向上键
            new_index = current_index - 1
            if new_index < 0:
                # 如果到达顶部，循环到最后一项
                new_index = count - 1
            self.setCurrentIndex(new_index)
            event.accept()
            return
        elif event.key() == QtCore.Qt.Key.Key_Down:
            # 向下键
            new_index = current_index + 1
            if new_index >= count:
                # 如果到达底部，循环到第一项
                new_index = 0
            self.setCurrentIndex(new_index)
            event.accept()
            return
            
        # 其他按键使用默认处理
        super().keyPressEvent(event)
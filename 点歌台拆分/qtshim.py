# -*- coding: utf-8 -*-
"""给 mainapp 用的最小适配层（R-15，PySide6 版）。

目的：mainapp 里原来那些 tkinter 调用（弹窗、取色、选文件、读写控件）
换成 Qt 的实现，但**调用写法不变**，把改动面压到最小：

  from qtshim import messagebox, filedialog, colorchooser     # 代替 from tkinter import ...
  entry.get() / entry.insert(0, "x") / entry.delete(0, "end")
  switch.get() / switch.select() / switch.deselect()
  label.configure(text="x", text_color="#f00")
  combo.get() / combo.set("x") / combo.configure(values=[...])

这些类就是 Qt 控件的薄包装，不改变外观，只让老代码能继续跑。
"""
import os

from PySide6.QtWidgets import QFileDialog, QColorDialog, QMessageBox, QWidget
from PySide6.QtGui import QColor

# ════════════ 控件适配器 ════════════

class LabelAdapter:
    """QLabel 的 tkinter 脸：configure(text=..., text_color=...)。"""

    def __init__(self, widget):
        self.w = widget

    def configure(self, **kw):
        w = self.w
        if "text" in kw:
            try:
                w.setText(str(kw["text"]))
            except Exception:
                pass
        color = kw.get("text_color")
        if color:
            try:
                c = QColor(color) if isinstance(color, str) else QColor(*color)
                w.setStyleSheet("color:%s;" % c.name())
            except Exception:
                pass
        if "font" in kw:
            try:
                w.setFont(kw["font"])
            except Exception:
                pass
        return self

    def pack(self, *a, **k):
        return self


class EntryAdapter:
    """QLineEdit / QSpinBox 的 tkinter 脸：get / insert / delete / configure(textvariable=...)。"""

    def __init__(self, widget):
        self.w = widget

    def get(self):
        w = self.w
        try:
            if hasattr(w, "text"):
                return w.text()
            if hasattr(w, "value"):
                return str(w.value())
        except Exception:
            pass
        return ""

    def insert(self, _index, text):
        try:
            if hasattr(self.w, "setText"):
                self.w.setText(str(text))
            else:
                self.w.setValue(int(float(str(text) or 0)))
        except Exception:
            pass

    def delete(self, _a, _b=None):
        try:
            if hasattr(self.w, "clear"):
                self.w.clear()
        except Exception:
            pass

    def configure(self, **kw):
        # 老代码里 configure(textvariable=...) 只用在 live_entry；Qt 用信号，不需要变量，直接忽略
        return self

    def set(self, value):
        self.insert(0, value)

    def pack(self, *a, **k):
        return self


class SwitchAdapter:
    def __init__(self, widget):
        self.w = widget

    def get(self):
        try:
            return bool(self.w.isChecked())
        except Exception:
            return False

    def select(self):
        try:
            self.w.setChecked(True)
        except Exception:
            pass

    def deselect(self):
        try:
            self.w.setChecked(False)
        except Exception:
            pass


class ComboAdapter:
    def __init__(self, widget):
        self.w = widget

    def get(self):
        try:
            return self.w.currentText()
        except Exception:
            return ""

    def set(self, text):
        try:
            self.w.setCurrentText(str(text))
        except Exception:
            pass

    def configure(self, **kw):
        return self

    def pack(self, *a, **k):
        return self


class SliderAdapter:
    def __init__(self, widget):
        self.w = widget

    def get(self):
        try:
            return self.w.value()
        except Exception:
            return 0

    def set(self, v):
        try:
            self.w.setValue(int(v))
        except Exception:
            pass


# ════════════ 弹窗 / 对话框（照 tkinter 的用法做）════════════

class _MessageBox:
    def _show(self, icon, title, msg):
        box = QMessageBox()
        box.setIcon(icon)
        box.setWindowTitle(str(title))
        box.setText(str(msg))
        box.exec()

    def showerror(self, title, msg):
        self._show(QMessageBox.Icon.Critical, title, msg)

    def showwarning(self, title, msg):
        self._show(QMessageBox.Icon.Warning, title, msg)

    def showinfo(self, title, msg):
        self._show(QMessageBox.Icon.Information, title, msg)

    def askyesno(self, title, msg):
        r = QMessageBox.question(None, str(title), str(msg))
        return r == QMessageBox.StandardButton.Yes


class _ColorChooser:
    def askcolor(self, color=None, **_kw):
        """返回 ((r,g,b), '#rrggbb')，与 tkinter.colorchooser 一致；取消返回 (None, None)。"""
        try:
            cur = QColor(color) if isinstance(color, str) and color else QColor("#FFFFFF")
        except Exception:
            cur = QColor("#FFFFFF")
        c = QColorDialog.getColor(cur)
        if not c.isValid():
            return (None, None)
        return ((c.red(), c.green(), c.blue()), c.name())


class _FileDialog:
    def askopenfilename(self, **_kw):
        path, _ = QFileDialog.getOpenFileName(None, "选择文件", "")
        return path


messagebox = _MessageBox()
colorchooser = _ColorChooser()
filedialog = _FileDialog()


# ════════════ 布局小工具 ════════════

def clear_layout(layout):
    """清空 QLayout 里所有控件（重建列表用）。"""
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()

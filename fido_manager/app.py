import sys
from pathlib import Path
import getpass
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from urllib.parse import urlparse

from PySide6.QtCore import Qt, QObject, Signal, QUrl, QTimer, QSize, QRectF
from PySide6.QtGui import QDesktopServices, QFont, QColor, QPainter
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout,
    QVBoxLayout, QLabel, QPushButton, QLineEdit, QComboBox, QListWidget,
    QListWidgetItem, QFrame, QDialog, QDialogButtonBox, QFormLayout, QMessageBox, QProgressBar, QStyledItemDelegate, QStyle, QScrollArea, QStackedWidget, QSizePolicy)
from fido2.ctap import CtapError
from .backend import Hardware, Demo, connection_snapshot, detection_help, operation_error, OperationCancelled
from .dialogs import PinDialog, ResetDialog
from .system_login import inspect as inspect_login, registrations

STYLE = """
QWidget { background: #f5f6f8; color: #202a3b; font-family: 'Inter', 'Noto Sans', sans-serif; font-size: 14px; }
QFrame#sidebar { background: #172332; border: none; }
QFrame#sidebar QLabel { color: #9faec0; }
QFrame#sidebar QLabel#brand { color: #f7faff; font-size: 19px; font-weight: 700; }
QLabel { background: transparent; }
QLabel#title { font-size: 28px; font-weight: 700; color: #172332; }
QLabel#brand { font-size: 19px; font-weight: 700; color: #24364d; }
QLabel#eyebrow { color: #788498; font-size: 11px; font-weight: 600; }
QLabel#muted { color: #667489; font-size: 12px; }
QLabel#sectionTitle { font-size: 16px; font-weight: 600; }
QLabel#badge { background: #e8eef5; color: #41546d; border-radius: 6px; padding: 5px 10px; font-size: 12px; }
QLabel#empty { color: #31445c; font-size: 17px; padding: 16px; }
QLabel#step { color: #64748b; background: #e9edf3; border-radius: 7px; padding: 10px 14px; font-size: 13px; }
QLabel#step[active="true"] { color: #164f9a; background: #deebff; font-weight: 700; }
QLabel#step[complete="true"] { color: #226348; background: #e3f1e9; }
QLabel#badge[unlocked="true"] { color: #226348; background: #e3f1e9; }
QLabel#operation { color: #254d81; background: #eaf1fc; border: 1px solid #cedff5; border-radius: 8px; padding: 12px 16px; }
QLabel#emptySymbol { color: #2868c6; font-size: 36px; font-weight: 700; }
QLabel#notice, QLabel#guidance { background: #eaf1fc; color: #254d81; border-radius: 8px; padding: 14px; }
QLabel#warning { background: #fff1e9; color: #924124; border-radius: 8px; padding: 14px; }
QFrame#card { background: #ffffff; border: 1px solid #e0e5eb; border-radius: 12px; }
QFrame#card QLabel { background: transparent; }
QWidget#detailFields { background: #ffffff; }
QFrame#dangerCard { background: #fffafa; border: 1px solid #edcece; border-radius: 12px; }
QPushButton { background: #ffffff; border: 1px solid #d4dce6; border-radius: 7px; padding: 9px 16px; font-weight: 600; }
QPushButton:hover { background: #edf2f8; border-color: #a7b8cd; }
QPushButton:focus { border: 2px solid #3375cf; }
QPushButton#primary { background: #2868c6; color: #ffffff; border: 1px solid #2868c6; }
QPushButton#primary:hover { background: #1c55a6; }
QPushButton#danger { color: #aa3535; background: #fffafa; border-color: #e2baba; }
QPushButton#danger:hover { color: #ffffff; background: #aa3535; }
QPushButton#disclosure { background: transparent; border: none; color: #3267ad; text-align: left; padding: 6px 0; font-size: 12px; }
QPushButton#disclosure:hover { text-decoration: underline; }
QPushButton#disclosure:focus { border: 1px solid #3375cf; }
QPushButton#nav { background: transparent; border: none; color: #aab9cc; text-align: left; padding: 12px 16px; }
QPushButton#nav:checked { background: #2d4058; color: #ffffff; }
QPushButton#nav:hover { background: #26364b; color: #ffffff; }
QPushButton#nav:focus { border: 1px solid #86ace1; }
QPushButton:disabled { color: #9aa5b5; background: #f0f2f5; border-color: #e5e9ef; }
QLineEdit, QComboBox { background: #ffffff; border: 1px solid #d4dce6; border-radius: 7px; padding: 10px; selection-background-color: #d3e4fb; selection-color: #142e53; }
QLineEdit:focus, QComboBox:focus { border-color: #3375cf; }
QLineEdit:disabled { color: #9aa5b5; background: #f0f2f5; }
QComboBox QAbstractItemView { background: #ffffff; selection-background-color: #dce9fa; selection-color: #172332; }
QListWidget { background: #ffffff; border: 1px solid #e0e5eb; border-radius: 12px; padding: 8px; outline: none; }
QListWidget:focus { border-color: #8eb0de; }
QProgressBar { background: #e5eaf0; border: none; border-radius: 2px; max-height: 4px; }
QProgressBar::chunk { background: #518bda; border-radius: 2px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #c7d0dc; min-height: 24px; border-radius: 3px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QDialog { background: #f5f6f8; }
QCheckBox { spacing: 10px; }
QToolTip { background: #172332; color: #ffffff; padding: 6px; border: none; }
"""

class PasskeyDelegate(QStyledItemDelegate):
    """Draw website and account separately, with local initials instead of favicons."""
    def sizeHint(self, option, index):
        return QSize(240, 76)

    def paint(self, painter, option, index):
        row = index.data(Qt.ItemDataRole.UserRole)
        if row is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(3, 3, -3, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.setPen(QColor('#c4d8f3') if selected else QColor('#ffffff'))
        painter.setBrush(QColor('#eaf2ff' if selected else '#f4f7fb' if hovered else '#ffffff'))
        painter.drawRoundedRect(QRectF(rect), 10, 10)
        avatar = QRectF(rect.left()+14, rect.top()+14, 42, 42)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(('#dce8fc', '#e4f0e9', '#eee5f8', '#f9ebd8')[sum(map(ord, row.rp)) % 4]))
        painter.drawRoundedRect(avatar, 12, 12)
        painter.setPen(QColor('#405c80'))
        font = QFont(option.font); font.setPointSize(14); font.setBold(True); painter.setFont(font)
        initials = row.rp.removeprefix('www.')[0:1].upper() or '?'
        painter.drawText(avatar, Qt.AlignmentFlag.AlignCenter, initials)
        left = rect.left()+70
        width = max(0, rect.width()-88)
        font.setPointSize(11); painter.setFont(font); painter.setPen(QColor('#20334e'))
        painter.drawText(left, rect.top()+29, painter.fontMetrics().elidedText(row.rp, Qt.TextElideMode.ElideRight, width))
        font.setBold(False); font.setPointSize(10); painter.setFont(font); painter.setPen(QColor('#69788c'))
        account = row.name or row.display_name or 'Unnamed account'
        painter.drawText(left, rect.top()+51, painter.fontMetrics().elidedText(account, Qt.TextElideMode.ElideRight, width))
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setPen(QColor('#3375cf')); painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(rect.adjusted(2,2,-2,-2)), 8, 8)
        painter.restore()

def label(text, style=None):
    w = QLabel(text)
    w.setTextFormat(Qt.TextFormat.PlainText)
    if style: w.setObjectName(style)
    w.setWordWrap(True)
    return w

def button(text, callback, style=None):
    w = QPushButton(text)
    w.setMinimumHeight(44)
    if style: w.setObjectName(style)
    w.clicked.connect(callback)
    return w

class OperationLabel(QLabel):
    """Keep feedback beside the device, and reclaim its space when idle."""
    def setText(self, text):
        super().setText(text)
        self.setVisible(bool(text))


class Bridge(QObject):
    done = Signal(object, object)
    progress = Signal(str)

class Window(QMainWindow):
    def __init__(self, demo=False, auto_scan=True):
        super().__init__()
        self.setWindowTitle("FIDO Manager" + (" — Demo" if demo else ""))
        self.resize(1180, 800)
        self.setMinimumSize(960, 700)
        self.backend = Demo() if demo else Hardware()
        self.demo = demo
        self.rows = []
        self.key_info = None
        self.unlocked = False
        self.busy = False
        self.reset_dialog = None
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.bridge = Bridge()
        self.bridge.done.connect(self.completed)
        root = QWidget(); self.setCentralWidget(root)
        outer = QHBoxLayout(root); outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)
        sidebar = QFrame(); sidebar.setObjectName("sidebar"); sidebar.setFixedWidth(204)
        side = QVBoxLayout(sidebar); side.setContentsMargins(14,30,14,24); side.setSpacing(8)
        side.addWidget(label("FIDO Manager", "brand"))
        side.addWidget(label("SECURITY KEY MANAGER", "eyebrow")); side.addSpacing(38)
        self.passkeys_nav = button("Saved passkeys", lambda: self.navigate(0), "nav")
        self.settings_nav = button("Key settings", lambda: self.navigate(1), "nav")
        for nav in (self.passkeys_nav, self.settings_nav):
            nav.setCheckable(True); side.addWidget(nav)
        side.addSpacing(18); side.addWidget(label("THIS COMPUTER", "eyebrow"))
        self.inventory_btn = button("Computer login…", self.key_inventory, "nav"); side.addWidget(self.inventory_btn)
        side.addStretch()
        side.addWidget(label("Stored on your key", "sectionTitle"))
        side.addWidget(label("PINs and passkeys are never saved to disk.", "muted"))
        if demo: side.addSpacing(12); side.addWidget(label("DEMO · SAMPLE DATA", "eyebrow"))
        outer.addWidget(sidebar)
        main = QVBoxLayout(); main.setContentsMargins(24,24,24,18); main.setSpacing(14); outer.addLayout(main,1)
        heading = QHBoxLayout()
        titles = QVBoxLayout(); titles.setSpacing(6)
        self.page_title = label("Saved passkeys", "title"); titles.addWidget(self.page_title)
        self.page_description = label("Your accounts, stored securely on this key.", "muted"); titles.addWidget(self.page_description)
        heading.addLayout(titles,1)
        self.add_btn = button("Add a website…", self.add_dialog); heading.addWidget(self.add_btn)
        main.addLayout(heading)

        device_card = QFrame(); device_card.setObjectName("card")
        device_row = QHBoxLayout(device_card); device_row.setContentsMargins(18,14,18,14); device_row.setSpacing(14)
        device_labels = QVBoxLayout(); device_labels.setSpacing(5)
        device_labels.addWidget(label("SECURITY KEY", "eyebrow"))
        self.devices = QComboBox(); self.devices.currentIndexChanged.connect(self.device_changed)
        self.devices.setMinimumContentsLength(18)
        self.devices.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.devices.setAccessibleName("Selected security key")
        self.devices.setPlaceholderText("No security key connected")
        device_labels.addWidget(self.devices); device_row.addLayout(device_labels,1)
        self.state = label("No key", "badge"); device_row.addWidget(self.state)
        self.scan_btn = button("Find keys", self.scan); device_row.addWidget(self.scan_btn)
        self.lock_btn = button("Lock passkeys", self.lock); device_row.addWidget(self.lock_btn)
        main.addWidget(device_card)

        self.steps = QWidget()
        step_layout = QHBoxLayout(self.steps); step_layout.setContentsMargins(0,0,0,0); step_layout.setSpacing(8)
        self.step_labels = []
        for text in ("1  Connect key", "2  Unlock with PIN", "3  Manage passkeys"):
            item = label(text, "step"); step_layout.addWidget(item,1); self.step_labels.append(item)
        main.addWidget(self.steps)
        self.status = OperationLabel(); self.status.setObjectName("operation")
        self.status.setWordWrap(True); self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setAccessibleName("Operation status"); self.status.hide(); main.addWidget(self.status)
        self.activity = QProgressBar(); self.activity.setRange(0,0); self.activity.setTextVisible(False)
        self.activity.hide(); main.addWidget(self.activity)
        self.pages = QStackedWidget(); main.addWidget(self.pages,1)
        passkeys = QWidget(); page = QVBoxLayout(passkeys); page.setContentsMargins(0,0,0,0); page.setSpacing(12)
        self.library_tools = QWidget(); tools = QHBoxLayout(self.library_tools); tools.setContentsMargins(0,0,0,0)
        self.search = QLineEdit(); self.search.setPlaceholderText("Search websites or accounts")
        self.search.setClearButtonEnabled(True); self.search.setAccessibleName("Search saved passkeys")
        self.search.textChanged.connect(self.render); tools.addWidget(self.search,1)
        self.refresh_btn = button("Reload passkeys", self.refresh); tools.addWidget(self.refresh_btn)
        page.addWidget(self.library_tools)
        self.storage_info = QWidget(); stats = QHBoxLayout(self.storage_info); stats.setContentsMargins(0,0,0,0)
        self.results = label("", "muted"); stats.addWidget(self.results); stats.addStretch()
        self.capacity = label("", "muted"); stats.addWidget(self.capacity); page.addWidget(self.storage_info)
        self.storage = QProgressBar(); self.storage.setTextVisible(False); self.storage.setRange(0,100); self.storage.setValue(0)
        page.addWidget(self.storage)
        content = QHBoxLayout(); content.setSpacing(16)
        self.list = QListWidget(); self.list.setItemDelegate(PasskeyDelegate(self.list))
        self.list.setSpacing(1); self.list.setMouseTracking(True)
        self.list.currentItemChanged.connect(self.show_selected); content.addWidget(self.list,3)
        self.empty_panel = QFrame(); self.empty_panel.setObjectName("card")
        empty_layout = QVBoxLayout(self.empty_panel); empty_layout.setContentsMargins(28,20,28,20); empty_layout.setSpacing(12)
        empty_layout.addStretch()
        self.empty_symbol = label("1", "emptySymbol"); self.empty_symbol.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_symbol)
        self.empty = label("Connect your security key", "empty"); self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty)
        self.unlock_form = QWidget(); self.unlock_form.setObjectName("detailFields")
        unlock_layout = QVBoxLayout(self.unlock_form); unlock_layout.setContentsMargins(0,0,0,0)
        pin_row = QHBoxLayout(); pin_row.addStretch()
        self.pin = QLineEdit(); self.pin.setPlaceholderText("Security key PIN"); self.pin.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin.setAccessibleName("Security key PIN"); self.pin.setMaximumWidth(240); self.pin.returnPressed.connect(self.unlock)
        pin_row.addWidget(self.pin)
        self.unlock_btn = button("Unlock passkeys", self.unlock, "primary"); pin_row.addWidget(self.unlock_btn); pin_row.addStretch()
        unlock_layout.addLayout(pin_row)
        self.pin_help = label("Use your key’s FIDO2 PIN, not your computer password.", "muted")
        self.pin_help.setAlignment(Qt.AlignmentFlag.AlignCenter); unlock_layout.addWidget(self.pin_help)
        empty_layout.addWidget(self.unlock_form)
        self.connect_btn = button("Find my security key", self.scan, "primary")
        empty_layout.addWidget(self.connect_btn,0,Qt.AlignmentFlag.AlignHCenter)
        self.empty_action = button("Open key settings", lambda: self.navigate(1))
        empty_layout.addWidget(self.empty_action,0,Qt.AlignmentFlag.AlignHCenter)
        self.clear_search_btn = button("Clear search", self.search.clear)
        empty_layout.addWidget(self.clear_search_btn,0,Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch(); content.addWidget(self.empty_panel,3)
        self.detail = QFrame(); self.detail.setObjectName("card")
        detail_layout = QVBoxLayout(self.detail); detail_layout.setContentsMargins(18,18,18,18); detail_layout.setSpacing(8)
        detail_fields = QWidget(); detail_fields.setObjectName("detailFields")
        dl = QVBoxLayout(detail_fields); dl.setContentsMargins(2,0,4,0); dl.setSpacing(6)
        field_scroll = QScrollArea(); field_scroll.setWidgetResizable(True); field_scroll.setWidget(detail_fields)
        detail_layout.addWidget(field_scroll,1)
        self.detail.setMinimumWidth(270); self.detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        dl.addWidget(label("SELECTED PASSKEY", "eyebrow"))
        self.rp = label("Select a passkey", "brand"); dl.addWidget(self.rp)
        dl.addWidget(label("Account", "muted")); self.account = label("—"); dl.addWidget(self.account)
        self.display_label = label("Display name", "muted"); dl.addWidget(self.display_label)
        self.display = label("—"); dl.addWidget(self.display)
        for value in (self.rp, self.account, self.display):
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); value.setMinimumWidth(0)
        self.technical_btn = button("Show credential ID", self.toggle_technical, "disclosure")
        self.technical_btn.setMinimumHeight(30); self.technical_btn.setCheckable(True); dl.addWidget(self.technical_btn)
        self.credid = label("—", "muted"); self.credid.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.credid.hide(); dl.addWidget(self.credid); dl.addStretch()
        self.edit_help = label("This key does not support renaming passkeys. You can still view or delete them.", "muted"); detail_layout.addWidget(self.edit_help)
        self.edit_btn = button("Rename on this key…", self.edit); detail_layout.addWidget(self.edit_btn)
        self.delete_btn = button("Delete passkey…", self.delete, "danger"); detail_layout.addWidget(self.delete_btn)
        content.addWidget(self.detail,2); page.addLayout(content,1)
        self.scope_btn = button("Missing a passkey?", self.explain_scope, "disclosure")
        self.scope_btn.setMinimumHeight(30)
        self.pages.addWidget(passkeys)

        settings_scroll = QScrollArea(); settings_scroll.setWidgetResizable(True)
        settings = QWidget(); settings_layout = QVBoxLayout(settings); settings_layout.setContentsMargins(0,0,4,0); settings_layout.setSpacing(16)
        self.settings_note = label("Connect a key to manage its PIN and reset options.", "notice"); settings_layout.addWidget(self.settings_note)
        pin_card = QFrame(); pin_card.setObjectName("card"); pin_layout = QVBoxLayout(pin_card); pin_layout.setContentsMargins(24,16,24,16); pin_layout.setSpacing(8)
        pin_layout.addWidget(label("Security key PIN", "sectionTitle"))
        self.pin_state = label("No key selected", "muted"); pin_layout.addWidget(self.pin_state)
        pin_layout.addWidget(label("Protect access to your passkeys. Changing the PIN keeps your saved accounts.", "muted"))
        self.pin_btn = button("Set up PIN", self.manage_pin, "primary"); pin_layout.addWidget(self.pin_btn,0,Qt.AlignmentFlag.AlignLeft)
        settings_layout.addWidget(pin_card)
        support_card = QFrame(); support_card.setObjectName("card"); support_layout = QVBoxLayout(support_card); support_layout.setContentsMargins(24,14,24,14)
        support_layout.addWidget(label("What this key supports", "sectionTitle"))
        self.support_info = label("Select a connected key to check its capabilities.", "muted"); support_layout.addWidget(self.support_info)
        settings_layout.addWidget(support_card)
        reset_card = QFrame(); reset_card.setObjectName("dangerCard"); reset_layout = QVBoxLayout(reset_card); reset_layout.setContentsMargins(24,16,24,16); reset_layout.setSpacing(8)
        reset_layout.addWidget(label("Reset FIDO", "sectionTitle"))
        reset_layout.addWidget(label("Start over if you forgot your PIN or the key is blocked. Reset erases passkeys and invalidates all FIDO sign-ins made with this key.", "muted"))
        self.reset_btn = button("Reset this key…", self.reset_key, "danger"); reset_layout.addWidget(self.reset_btn,0,Qt.AlignmentFlag.AlignLeft)
        settings_layout.addWidget(reset_card); settings_layout.addStretch()
        settings_scroll.setWidget(settings); self.pages.addWidget(settings_scroll)
        footer = QHBoxLayout()
        footer.addWidget(label("Only passkeys stored on the selected physical key appear here.", "muted"),1)
        footer.addWidget(self.scope_btn); main.addLayout(footer)
        self.navigate(0); self.render()
        self.connection_state = connection_snapshot() if not demo else None
        self.connection_timer = QTimer(self); self.connection_timer.timeout.connect(self.check_connections)
        if not demo: self.connection_timer.start(1500)
        if auto_scan: QTimer.singleShot(0,self.scan)

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        self.steps.setVisible(index == 0)
        self.passkeys_nav.setChecked(index == 0); self.settings_nav.setChecked(index == 1)
        self.page_title.setText("Saved passkeys" if index == 0 else "Key settings")
        self.page_description.setText("View and manage the website accounts saved on your security key." if index == 0 else
                                      "Manage your PIN, check capabilities, or start over.")
        self.add_btn.setVisible(index == 0 and self.unlocked)
        self.scope_btn.setVisible(index == 0)

    def check_connections(self):
        if self.busy or self.reset_dialog: return
        snapshot = connection_snapshot()
        if snapshot is not None and snapshot != self.connection_state:
            self.scan()

    def controls(self):
        connected = self.devices.count() > 0
        info = self.key_info
        ready = connected and not self.busy
        usable = info is not None and (info.pin_set and info.credential_management and not info.force_pin_change
                                  and info.retries != 0 and not info.temporarily_blocked)
        self.activity.setVisible(self.busy)
        state = "Unlocked" if self.unlocked else "Locked" if connected else "No key"
        if info and not self.unlocked:
            state = "PIN blocked" if info.retries == 0 else "Set PIN" if info.pin_set is False else "Locked" if usable else "Connected"
        self.state.setText("Working…" if self.busy else state)
        self.state.setProperty("unlocked", self.unlocked)
        self.state.style().unpolish(self.state); self.state.style().polish(self.state)
        stage = 2 if self.unlocked else 1 if connected else 0
        for index, item in enumerate(self.step_labels):
            item.setProperty("active", index == stage)
            item.setProperty("complete", index < stage)
            item.style().unpolish(item); item.style().polish(item)
        self.empty_symbol.setText("✓" if self.unlocked else "2" if connected else "1")
        self.connect_btn.setVisible(not connected)
        self.connect_btn.setEnabled(not self.busy)
        self.lock_btn.setVisible(self.unlocked); self.lock_btn.setEnabled(not self.busy)
        self.unlock_form.setVisible(connected and not self.unlocked and bool(usable))
        self.empty_action.setVisible(connected and not self.unlocked)
        self.empty_action.setText("Forgot PIN? Open key settings" if usable else "Open key settings")
        self.empty_action.setEnabled(not self.busy)
        self.library_tools.setVisible(self.unlocked); self.storage_info.setVisible(self.unlocked)
        self.storage.setVisible(self.unlocked)
        self.edit_help.setVisible(self.unlocked and not self.backend.can_edit)
        self.detail.setVisible(self.unlocked and self.selected() is not None)
        self.inventory_btn.setEnabled(not self.busy)
        for widget in (self.scan_btn, self.devices): widget.setEnabled(not self.busy)
        self.unlock_btn.setEnabled(ready and bool(usable) and not self.unlocked)
        self.pin.setEnabled(ready and bool(usable) and not self.unlocked)
        self.pin_help.setText(("Demo: leave the PIN empty and click Unlock passkeys" if self.demo else "Key PIN, not your computer password") +
                              (f" · {info.retries} attempts left" if info and info.retries is not None else ""))
        self.refresh_btn.setEnabled(self.unlocked and not self.busy)
        self.add_btn.setEnabled(not self.busy)
        self.add_btn.setVisible(self.pages.currentIndex() == 0 and self.unlocked)
        selected = self.selected() is not None
        self.edit_btn.setEnabled(self.unlocked and selected and self.backend.can_edit and not self.busy)
        self.delete_btn.setEnabled(self.unlocked and selected and not self.busy)
        self.search.setEnabled(self.unlocked and not self.busy)
        self.reset_btn.setEnabled(ready and info is not None and info.fido2)
        self.pin_btn.setEnabled(ready and info is not None and info.pin_set is not None
                                and info.retries != 0 and not info.temporarily_blocked)
        self.pin_btn.setText("Change PIN…" if info and info.pin_set else "Set up PIN…")
        if not connected:
            note = "Connect a key to manage its PIN and reset options."
            pin_status = "No key selected"
            support = "Select a connected key to check its capabilities."
        elif info is None:
            note = "Checking this key’s capabilities. Rescan if the key cannot be read."
            pin_status = "Key information unavailable"
            support = "Capability information is not available yet."
        else:
            note = ("PIN blocked. Reset FIDO to use this key again." if info.retries == 0 else
                    "PIN temporarily blocked. Unplug and reconnect before trying again." if info.temporarily_blocked else
                    "Your key requires a PIN change before it can be used." if info.force_pin_change else
                    "Set a PIN to start using this key’s passkeys." if info.pin_set is False else
                    "This key does not support FIDO2 management. Use its manufacturer’s tool." if not info.fido2 else
                    "Manage the selected key. You do not need to unlock passkeys to change its PIN or reset it.")
            pin_status = ("PIN is set" if info.pin_set else "No PIN set" if info.pin_set is False else "PIN management unavailable")
            if info.retries is not None: pin_status += f" · {info.retries} attempts remaining"
            support = ("FIDO2 supported" if info.fido2 else "FIDO2 unavailable") + "  ·  " + (
                "Passkey browsing supported" if info.credential_management else "Passkey browsing unavailable")
        self.settings_note.setText(note); self.pin_state.setText(pin_status); self.support_info.setText(support)
        self.settings_note.setVisible(not connected or info is None or not info.fido2 or
                                      info.pin_set is False or info.retries == 0 or
                                      info.temporarily_blocked or info.force_pin_change)

    def key_inventory(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("All keys & computer login")
        dialog.resize(760, 650)
        layout = QVBoxLayout(dialog)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        body = QWidget(); content = QVBoxLayout(body); content.setSpacing(14)
        content.addWidget(label("Keys & computer login", "title"))
        content.addWidget(label("Connected hardware", "sectionTitle"))
        if not self.devices.count():
            content.addWidget(label("No accessible FIDO key connected. " + detection_help(), "muted"))
        for index in range(self.devices.count()):
            current = index == self.devices.currentIndex()
            status = "Connected · passkeys unlocked" if current and self.unlocked else "Connected · passkeys locked"
            name = label(f"{index + 1}. {self.devices.itemText(index)} — {status}")
            name.setTextFormat(Qt.TextFormat.PlainText); content.addWidget(name)
        content.addWidget(label("Registered for computer login", "sectionTitle"))
        rows, issues = ([], []) if self.demo else registrations()
        if self.demo:
            content.addWidget(label("Demo mode: computer login registrations are not inspected.", "muted"))
        elif not rows:
            content.addWidget(label("No readable login registrations found for your user.", "muted"))
        for index, row in enumerate(rows, 1):
            card = QFrame(); card.setObjectName("card"); registration = QVBoxLayout(card)
            registration.setContentsMargins(16,12,16,12)
            item = label(f"Login key {index} · {row['user']}", "sectionTitle")
            item.setTextFormat(Qt.TextFormat.PlainText); registration.addWidget(item)
            registration.addWidget(label("Registered · connection unknown", "muted"))
            details = label(f"Registration: {row['fingerprint']}\nMapping: {row['source']}", "muted")
            details.setTextFormat(Qt.TextFormat.PlainText)
            details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); details.hide()
            toggle = QPushButton("Registration details"); toggle.setObjectName("disclosure")
            toggle.setCheckable(True); toggle.toggled.connect(details.setVisible)
            registration.addWidget(toggle); registration.addWidget(details); content.addWidget(card)
        for issue in issues:
            item = label(issue, "muted"); item.setTextFormat(Qt.TextFormat.PlainText); content.addWidget(item)
        content.addWidget(label("Registrations stay listed when unplugged. They cannot be matched to a connected key. This app keeps no history of unregistered keys.", "muted"))
        content.addWidget(label("Where key login is configured", "sectionTitle"))
        services, error = ([], "Demo mode") if self.demo else inspect_login()
        for _, name, enabled in services:
            content.addWidget(label(name + (" · Key authentication configured · test required" if enabled else " · Key authentication not configured")))
        if error: content.addWidget(label(error, "muted"))
        content.addWidget(label("How to sign in with your key", "sectionTitle"))
        content.addWidget(label("1. Connect your registered key.\n2. Leave the computer password field empty and press Enter or Sign in.\n3. When the key flashes / requests a touch, press its button.\nYou can still use your computer password as a fallback.", "guidance"))
        content.addStretch(); scroll.setWidget(body); layout.addWidget(scroll)
        configure = button("Configure computer login…", lambda: (dialog.accept(), self.login_setup()))
        configure.setEnabled(not self.demo); layout.addWidget(configure)
        layout.addWidget(button("Close", dialog.accept)); dialog.exec()

    def inspect_selected(self, after=None):
        index = self.devices.currentIndex()
        if index < 0: return
        def inspected(info):
            self.key_info = info
            self.render()
            self.status.setText("")
            if after: after()
        self.run(lambda: self.backend.inspect_key(index), inspected, "Checking key capabilities…")

    def manage_pin(self):
        if self.busy or not self.key_info or not self.pin_btn.isEnabled(): return
        dialog = PinDialog(self.key_info, self.devices.currentText(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            dialog.deleteLater()
            return
        new_pin, old_pin = dialog.take_values(); dialog.deleteLater()
        index = self.devices.currentIndex()
        self.clear()
        def saved(_):
            self.inspect_selected(lambda: self.status.setText("PIN saved. Open Saved passkeys and unlock with your new PIN."))
        def failed(error):
            message = operation_error(error)
            self.inspect_selected(lambda: self.status.setText(message))
        self.run(lambda: self.backend.set_pin(index, new_pin, old_pin), saved, "Saving PIN…", failed)

    def reset_key(self):
        if self.busy or not self.reset_btn.isEnabled(): return
        index = self.devices.currentIndex()
        dialog = ResetDialog(self.devices.currentText(), self.key_info.serial, self.demo, self)
        cancel = Event()
        self.reset_dialog = dialog
        self.bridge.progress.connect(dialog.message.setText)
        outcome = []
        def success(_):
            message = "Reset complete. Set a new PIN in Key settings, then register the key again with your accounts and computer."
            outcome.append(message); dialog.complete(message)
        def failed(error):
            message = operation_error(error)
            if not isinstance(error, OperationCancelled):
                message = "Reset was not confirmed. " + message
            outcome.append(message); dialog.complete(message)
        def start():
            self.clear(); self.key_info = None
            self.run(lambda: self.backend.reset(index, cancel, self.bridge.progress.emit), success,
                     "Reset in progress… Follow the steps in the reset window.", failed)
        dialog.start_requested.connect(start)
        dialog.cancel_requested.connect(cancel.set)
        dialog.exec()
        self.bridge.progress.disconnect(dialog.message.setText)
        self.reset_dialog = None
        dialog.deleteLater()
        if outcome:
            # Reset closes the old handles even when cancelled; reload capabilities.
            self.scan(after=lambda: self.status.setText(outcome[-1]))

    def login_setup(self):
        services, error = inspect_login()
        if error:
            QMessageBox.information(self, "Computer login", error)
            return
        report = "\n".join(label + (": PAM module present (test required)" if enabled
                                   else ": setup needed")
                           for _, label, enabled in services)
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Computer login setup")
        dialog.setText(report)
        dialog.setInformativeText(
            "Passkey management and computer login use separate registrations. "
            "Setup reuses an existing registration or enrolls your key for this user. "
            "On Fedora it installs missing enrollment tools. Connect only the key you want to register. "
            "It enables detected login and screen unlock services, preserves password fallback, "
            "and creates backups. Administrator authentication is required. "
            "After approving the administrator prompt, touch your key when it flashes (within 90 seconds). "
            "To test: leave the password empty, submit with Enter / Sign in, then touch the key when prompted.")
        setup = dialog.addButton("Set up detected services", QMessageBox.ButtonRole.AcceptRole)
        dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.exec()
        if dialog.clickedButton() != setup:
            return
        helper = Path(__file__).resolve().parent.parent / "repair-plasma-login.py"
        pkexec = shutil.which("pkexec")
        if not pkexec or not helper.is_file():
            QMessageBox.warning(self, "Setup unavailable", "Install polkit (pkexec) and the bundled login setup helper.")
            return
        username = getpass.getuser()
        def configure():
            result = subprocess.run([pkexec, "/usr/bin/python3", str(helper),
                                     "--user", username, "--enroll"], capture_output=True, text=True)
            if result.returncode:
                raise ValueError(result.stderr.strip() or result.stdout.strip() or "Administrator authentication was cancelled.")
            return result.stdout.strip()
        self.run(configure, lambda text: QMessageBox.information(self, "Computer login setup", text),
                 "Setting up computer login · approve the administrator prompt, then touch your key when it flashes…")

    def run(self, job, callback, message, on_error=None):
        if self.busy: return
        self.busy=True; self.controls(); self.status.setText(message)
        future=self.executor.submit(job)
        def done(f):
            try: result=f.result()
            except Exception as exc: self.bridge.done.emit((False,exc),(callback,on_error))
            else: self.bridge.done.emit((True,result),(callback,on_error))
        future.add_done_callback(done)

    def completed(self,result,callback):
        self.busy=False
        ok,value=result
        success, failure = callback
        if ok: success(value)
        elif failure: failure(value)
        else:
            message = operation_error(value)
            if isinstance(value, CtapError) and value.code in (
                    CtapError.ERR.PIN_TOKEN_EXPIRED, CtapError.ERR.PIN_AUTH_INVALID,
                    CtapError.ERR.PUAT_REQUIRED):
                self.clear()
                self.executor.submit(self.backend.lock)
            self.status.setText(message)
            QMessageBox.warning(self,"Key operation failed",message)
        self.controls()

    def clear(self):
        self.unlocked=False; self.rows=[]; self.list.clear(); self.pin.clear()
        self.search.clear()
        self.capacity.setText("—"); self.state.setText("Locked")
        self.storage.setValue(0); self.storage.setToolTip("Unlock your key to see storage usage")
        self.render()

    def device_changed(self):
        self.clear()
        self.key_info = None
        self.status.setText("")
        if not self.busy:
            self.executor.submit(self.backend.lock)
            self.inspect_selected()
        self.controls()

    def scan(self, _checked=False, after=None):
        if self.busy: return
        self.connection_state = connection_snapshot() if not self.demo else None
        self.key_info = None
        self.clear()
        def loaded(names):
            self.devices.blockSignals(True); self.devices.clear(); self.devices.addItems(names)
            if names: self.devices.setCurrentIndex(0)
            self.devices.blockSignals(False)
            self.devices.setToolTip("\n".join(names))
            self.status.setText("")
            self.render()
            if not names: self.empty.setText(detection_help())
            if names:
                self.pin.setFocus()
                self.inspect_selected(after)
            elif after: after()
        self.run(self.backend.scan,loaded,"Looking for security keys…")

    def unlock(self):
        if self.busy or self.unlocked or self.devices.currentIndex()<0: return
        pin=self.pin.text(); self.pin.clear()
        if not pin and not self.demo:
            self.status.setText("Enter your security key PIN first."); self.pin.setFocus(); return
        index=self.devices.currentIndex()
        def failed(error):
            message = operation_error(error)
            self.clear()
            self.inspect_selected(lambda: self.status.setText(message))
        self.run(lambda:self.backend.unlock(index,pin),self.loaded,"Unlocking your key…",failed)

    def lock(self):
        self.clear()
        self.run(self.backend.lock,lambda _:self.status.setText("Session locked."),"Locking…")

    def loaded(self,data):
        self.rows,remaining=data; self.unlocked=True
        self.capacity.setText(f"{remaining} slots available"); self.state.setText("Unlocked")
        total = len(self.rows) + remaining
        self.storage.setValue(round(100 * len(self.rows) / total) if total else 0)
        self.storage.setToolTip(f"{len(self.rows)} used · {remaining} available slots")
        self.render(); self.status.setText("Storage full. Delete an unused passkey to make room." if remaining == 0 else
                                          "Passkeys refreshed." if not self.demo else "Demo · changes last until you close the app.")

    def refresh(self): self.run(self.backend.read,self.loaded,"Reading stored passkeys…")

    def selected(self):
        item=self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def render(self):
        previous=self.selected(); self.list.clear(); needle=self.search.text().strip().casefold()
        for row in sorted(self.rows,key=lambda r:(r.rp,r.name)):
            if needle not in f"{row.rp} {row.name} {row.display_name}".casefold(): continue
            item=QListWidgetItem(f"{row.rp}\n{row.name or row.display_name or 'Unnamed account'}")
            item.setToolTip(f"{row.rp}\n{row.name or row.display_name or 'Unnamed account'}")
            item.setData(Qt.ItemDataRole.UserRole,row); self.list.addItem(item)
            if previous and row.credential_id==previous.credential_id: self.list.setCurrentItem(item)
        if not self.list.currentItem() and self.list.count(): self.list.setCurrentRow(0)
        if not self.list.count():
            self.rp.setText("No matches" if self.rows else "No stored passkeys" if self.unlocked else "Unlock your key")
        matches = self.list.count()
        self.results.setText((f"{matches} of {len(self.rows)} passkeys" if needle else
                              f"{matches} passkey" + ("" if matches == 1 else "s")) if self.unlocked else "")
        self.list.setVisible(self.list.count() > 0)
        self.empty_panel.setVisible(self.list.count() == 0)
        self.clear_search_btn.setVisible(self.unlocked and bool(needle))
        self.empty.setText("No matching passkeys\n\nTry a different search, or clear it to see all your accounts." if self.rows else
                           "No saved passkeys\n\nAdd this key in a website’s security settings, then click Reload passkeys." if self.unlocked else
                           "Unlock your passkeys\n\nEnter this security key’s PIN to see your accounts." if self.devices.count() else
                           "Connect a security key\n\nPlug in your key to browse passkeys or manage its PIN.")
        info = self.key_info
        if self.devices.count() and info is None and not self.unlocked:
            self.empty.setText("Checking your security key\n\nPlease wait while we read its capabilities. If this does not finish, click Find keys to retry.")
        if info and not self.unlocked:
            reason = ("This key’s PIN is blocked.\n\nReset FIDO in Key settings to start over." if info.retries == 0 else
                      "PIN temporarily blocked\n\nUnplug and reconnect the key before trying again." if info.temporarily_blocked else
                      "Change your PIN to continue\n\nYour key requires a new PIN. Open Key settings." if info.force_pin_change else
                      "Set up your security key\n\nCreate a PIN in Key settings, then unlock your passkeys." if info.pin_set is False else
                      "Passkey browsing unavailable\n\nThis key does not support listing saved passkeys." if not info.credential_management else
                      "PIN unlock unavailable\n\nUse your key’s manufacturer tool to manage this device." if info.pin_set is None else None)
            if reason: self.empty.setText(reason)
        self.controls()

    def show_selected(self,*_):
        row=self.selected()
        self.rp.setText(row.rp if row else "Select a passkey")
        self.account.setText(row.name or "Unnamed account" if row else "—")
        self.display.setText(row.display_name or "—" if row else "—")
        has_display = bool(row and row.display_name and row.display_name != row.name)
        self.display.setVisible(has_display); self.display_label.setVisible(has_display)
        self.technical_btn.setChecked(False); self.credid.hide()
        self.technical_btn.setText("Show credential ID")
        hex_id = row.credential_id.hex() if row else ""
        self.credid.setToolTip(hex_id)
        self.credid.setText(" ".join(hex_id[i:i+16] for i in range(0,len(hex_id),16)) if row else "—")
        self.controls()

    def toggle_technical(self):
        expanded = self.technical_btn.isChecked()
        self.credid.setVisible(expanded)
        self.technical_btn.setText("Hide credential ID" if expanded else "Show credential ID")

    def explain_scope(self):
        QMessageBox.information(self, "Missing a passkey?",
            "This list shows discoverable passkeys stored on the selected security key.\n\n"
            "Passkeys saved in your browser, phone, or password manager are stored elsewhere. "
            "Older U2F and non-discoverable credentials cannot be listed here.\n\n"
            "Check the selected key, then click Reload passkeys after adding a passkey on a website.")

    def fields(self,title,row=None,with_pin=False):
        dialog=QDialog(self); dialog.setWindowTitle(title); dialog.setMinimumWidth(440)
        form=QFormLayout(dialog); form.setContentsMargins(24,24,24,24); form.setSpacing(16)
        name=QLineEdit(row.name if row else ""); display=QLineEdit(row.display_name if row else "")
        name.setMaxLength(64); display.setMaxLength(64)
        form.addRow("Account name",name); form.addRow("Display name",display)
        pin=QLineEdit(); pin.setEchoMode(QLineEdit.EchoMode.Password)
        if with_pin:
            form.addRow(label("Creates a local test credential on this key. It will not sign you into a website. Touch your key when prompted.","muted"))
            form.addRow("Key PIN",pin)
        else: form.addRow(label("Edits the name stored on your key. Your website account stays the same.","muted"))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); form.addRow(buttons)
        buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
        def validate():
            valid=bool(name.text().strip()) and len(name.text().encode())<=64 and len(display.text().encode())<=64
            if with_pin: valid=valid and (bool(pin.text()) or self.demo)
            buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(valid)
        name.textChanged.connect(validate); display.textChanged.connect(validate); pin.textChanged.connect(validate); validate()
        if dialog.exec()!=QDialog.DialogCode.Accepted: return None
        value=(name.text().strip(),display.text().strip(),pin.text()); pin.clear(); return value

    def edit(self):
        row=self.selected()
        if not row: return
        values=self.fields("Edit passkey",row)
        if values:
            name,display,_=values
            self.run(lambda:self.backend.update(row,name,display),self.loaded,"Saving account details…")

    def delete(self):
        row=self.selected()
        if not row: return
        dialog=QMessageBox(QMessageBox.Icon.Warning,"Delete passkey?",
            f"Permanently delete the passkey for {row.name or 'this account'} at {row.rp}?\n\nThis cannot be undone. Make sure you have another way to sign in.",
            QMessageBox.StandardButton.Cancel|QMessageBox.StandardButton.Yes,self)
        dialog.button(QMessageBox.StandardButton.Yes).setText("Delete permanently")
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if dialog.exec()==QMessageBox.StandardButton.Yes:
            self.run(lambda:self.backend.delete(row),self.loaded,"Deleting selected passkey…")

    def add_dialog(self):
        dialog=QDialog(self); dialog.setWindowTitle("Add a passkey"); dialog.setMinimumWidth(470)
        layout=QVBoxLayout(dialog); layout.setContentsMargins(28,28,28,28); layout.setSpacing(18)
        layout.addWidget(label("Add a new passkey","brand"))
        layout.addWidget(label("1. Open the website where you want to use this key.\n2. In its security settings, choose Add passkey or Security key.\n3. Follow the website’s instructions, then return here and click Reload passkeys.","muted"))
        url=QLineEdit(); url.setPlaceholderText("https://example.com/account/security"); layout.addWidget(url)
        def website():
            parsed=urlparse(url.text().strip())
            if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password:
                QMessageBox.warning(dialog,"Website address","Enter an HTTPS website address."); return
            QDesktopServices.openUrl(QUrl(url.text().strip())); dialog.accept()
        layout.addWidget(button("Open website registration",website,"primary"))
        layout.addWidget(label("Or create a local test credential to try your key's capabilities.","muted"))
        def local():
            dialog.accept()
            values=self.fields("Create local test passkey",with_pin=True)
            if values:
                name,display,pin=values
                self.run(lambda:self.backend.create_local(pin,name,display),self.loaded,"Creating local passkey · touch your security key (45s timeout)…")
        create=button("Create local test passkey",local); create.setEnabled(self.unlocked); layout.addWidget(create)
        layout.addWidget(button("Cancel",dialog.reject)); dialog.exec()

    def closeEvent(self,event):
        if self.busy:
            self.status.setText("Wait for the current operation to finish before closing."); event.ignore(); return
        self.executor.submit(self.backend.close).result()
        self.executor.shutdown(wait=True); event.accept()

def main():
    app=QApplication(sys.argv); app.setStyle("Fusion"); app.setStyleSheet(STYLE); app.setFont(QFont("Noto Sans",10))
    window=Window("--demo" in sys.argv); window.show()
    return app.exec()

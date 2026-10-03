"""Key settings dialogs; hardware work stays on the window's worker thread."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout, QProgressBar,
)
from .backend import validate_pin


def text(value, style=None):
    widget = QLabel(value)
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if style:
        widget.setObjectName(style)
    return widget


class PinDialog(QDialog):
    def __init__(self, info, key_name, parent=None):
        super().__init__(parent)
        self.info = info
        self.setWindowTitle('Change PIN' if info.pin_set else 'Set a PIN')
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(16)
        layout.addWidget(text(self.windowTitle(), 'title'))
        layout.addWidget(text(key_name, 'muted'))
        layout.addWidget(text('This PIN protects access to the key. Changing it keeps your existing passkeys.', 'muted'))
        form = QFormLayout()
        form.setSpacing(12)
        self.old = QLineEdit()
        self.new = QLineEdit()
        self.confirm = QLineEdit()
        for field in (self.old, self.new, self.confirm):
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setMaxLength(63)
            field.textChanged.connect(self.validate)
        if info.pin_set:
            form.addRow('Current PIN', self.old)
        form.addRow('New PIN', self.new)
        form.addRow('Confirm PIN', self.confirm)
        layout.addLayout(form)
        self.hint = text(f'At least {info.min_pin_length} characters; up to {info.max_pin_length} UTF-8 bytes.', 'muted')
        layout.addWidget(self.hint)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName('primary')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.validate()

    def validate(self):
        if not hasattr(self, 'buttons'):
            return
        error = validate_pin(self.new.text(), self.info.min_pin_length, self.info.max_pin_length)
        if not error and self.new.text() != self.confirm.text():
            error = 'The new PINs must match.'
        if not error and self.info.pin_set and not self.old.text():
            error = 'Enter your current PIN.'
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(not error)
        if self.new.text() or self.confirm.text():
            self.hint.setText(error or 'Ready to save.')

    def take_values(self):
        values = (self.new.text(), self.old.text() if self.info.pin_set else None)
        self.clear_values()
        return values

    def clear_values(self):
        for field in (self.old, self.new, self.confirm):
            field.clear()

    def reject(self):
        self.clear_values()
        super().reject()


class ResetDialog(QDialog):
    start_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, key_name, serial=None, demo=False, parent=None):
        super().__init__(parent)
        self.running = False
        self.finished = False
        self.setWindowTitle('Reset FIDO')
        self.setMinimumSize(560, 660)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 28)
        layout.setSpacing(16)
        layout.addWidget(text('Reset this security key?', 'title'))
        layout.addWidget(text(key_name, 'sectionTitle'))
        layout.addWidget(text(
            'Reset removes the FIDO PIN and saved passkeys, and invalidates all FIDO sign-ins '
            'made with this key, including older security-key and computer-login registrations. '
            'It cannot be undone.', 'warning'))
        layout.addWidget(text('After reset, set a new PIN and register the key again with each service. '
                              'Other applications on a multi-purpose key are outside this FIDO reset.', 'muted'))
        if demo:
            layout.addWidget(text('Demo only. Reset clears sample passkeys; no hardware is accessed.', 'notice'))
        elif serial:
            layout.addWidget(text(f'Selected key serial: {serial}', 'muted'))
        else:
            layout.addWidget(text('This key has no serial number. Identical models cannot be distinguished. '
                                  'Reconnect only the physical key you intend to erase.', 'muted'))
        self.ack = QCheckBox('I have another way to sign in to my accounts and computer.')
        layout.addWidget(self.ack)
        self.confirm = QLineEdit()
        self.confirm.setPlaceholderText('Type RESET to continue')
        self.confirm.setAccessibleName('Type RESET to confirm erasing FIDO credentials')
        layout.addWidget(self.confirm)
        self.message = text('Next: unplug your keys, reconnect the selected key, and touch it.', 'muted')
        layout.addWidget(self.message)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.buttons = QDialogButtonBox()
        self.cancel_btn = self.buttons.addButton('Cancel', QDialogButtonBox.ButtonRole.RejectRole)
        self.start_btn = self.buttons.addButton('Continue to reset', QDialogButtonBox.ButtonRole.ActionRole)
        self.start_btn.setObjectName('danger')
        self.start_btn.setEnabled(False)
        self.start_btn.setAutoDefault(False)
        self.cancel_btn.setDefault(True)
        self.cancel_btn.clicked.connect(self.reject)
        self.start_btn.clicked.connect(self.start)
        self.ack.toggled.connect(self.validate)
        self.confirm.textChanged.connect(self.validate)
        layout.addWidget(self.buttons)

    def validate(self):
        self.start_btn.setEnabled(self.ack.isChecked() and self.confirm.text() == 'RESET' and not self.running)

    def start(self):
        if not self.start_btn.isEnabled() or self.finished:
            return
        self.running = True
        self.ack.setEnabled(False)
        self.confirm.setEnabled(False)
        self.start_btn.hide()
        self.progress.show()
        self.start_requested.emit()

    def complete(self, message):
        self.running = False
        self.finished = True
        self.progress.hide()
        self.message.setText(message)
        self.cancel_btn.setText('Done')
        self.cancel_btn.setEnabled(True)

    def reject(self):
        if self.running:
            self.cancel_requested.emit()
            self.cancel_btn.setEnabled(False)
            self.message.setText('Cancelling… Wait for the key to respond. A completed reset cannot be undone.')
            return
        super().reject()

    def closeEvent(self, event):
        if self.running:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)

import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialogButtonBox
from fido2.ctap import CtapError
from fido_manager.backend import Hardware, Demo, KeyInfo, OperationCancelled, operation_error, validate_pin
from fido_manager.dialogs import PinDialog, ResetDialog
from fido_manager.app import Window, STYLE


def descriptor(serial='chosen', pid=1):
    return SimpleNamespace(vid=10, pid=pid, serial_number=serial, path='/fake/key')


def reset_hardware():
    hardware = Hardware()
    device = Mock()
    device.descriptor = descriptor()
    hardware.devices = [device]
    hardware.manager = Mock()
    return hardware, device


def test_reset_requires_removal_and_matching_reconnection_then_closes_handles():
    hardware, original = reset_hardware()
    reconnected = Mock(); reconnected.descriptor = descriptor()
    ctap = Mock()
    ctap.info.aaguid = b'model'
    with patch('fido_manager.backend.Ctap2', return_value=ctap), \
         patch('fido_manager.backend.list_descriptors', side_effect=[[descriptor()], [], [descriptor()]]), \
         patch('fido_manager.backend.open_device', return_value=reconnected) as opened:
        progress = Mock(); cancel = Event()
        hardware.reset(0, cancel, progress)
    ctap.reset.assert_called_once_with(event=cancel)
    opened.assert_called_once_with('/fake/key')
    assert progress.call_count == 3
    original.close.assert_called_once()
    reconnected.close.assert_called_once()
    assert hardware.manager is None and hardware.devices == []


@pytest.mark.parametrize('candidates', [
    [descriptor(serial='wrong')], [descriptor(pid=2)], [descriptor(), descriptor()],
])
def test_reset_rejects_wrong_or_multiple_keys(candidates):
    hardware, _ = reset_hardware()
    with patch('fido_manager.backend.Ctap2') as ctap, \
         patch('fido_manager.backend.list_descriptors', side_effect=[[], candidates]), \
         patch('fido_manager.backend.open_device') as opened:
        with pytest.raises(ValueError):
            hardware.reset(0, Event(), Mock())
    ctap.return_value.reset.assert_not_called()
    opened.assert_not_called()


def test_reset_checks_model_again_after_reconnect():
    hardware, _ = reset_hardware()
    original_ctap, new_ctap = Mock(), Mock()
    original_ctap.info.aaguid = b'one'; new_ctap.info.aaguid = b'two'
    reconnected = Mock(); reconnected.descriptor = descriptor()
    with patch('fido_manager.backend.Ctap2', side_effect=[original_ctap, new_ctap]), \
         patch('fido_manager.backend.list_descriptors', side_effect=[[], [descriptor()]]), \
         patch('fido_manager.backend.open_device', return_value=reconnected):
        with pytest.raises(ValueError, match='does not match'):
            hardware.reset(0, Event(), Mock())
    new_ctap.reset.assert_not_called()
    reconnected.close.assert_called_once()


def test_reset_cancel_before_request_never_sends_reset():
    hardware, _ = reset_hardware()
    cancel = Event(); cancel.set()
    with patch('fido_manager.backend.Ctap2') as ctap:
        with pytest.raises(OperationCancelled): hardware.reset(0, cancel, Mock())
    ctap.return_value.reset.assert_not_called()


def test_reset_reconnect_timeout_never_sends_reset():
    hardware, _ = reset_hardware()
    with patch('fido_manager.backend.Ctap2') as ctap:
        with pytest.raises(TimeoutError): hardware.reset(0, Event(), Mock(), reconnect_timeout=0)
    ctap.return_value.reset.assert_not_called()


def test_reset_timeout_or_denial_is_not_retried():
    hardware, _ = reset_hardware()
    ctap = Mock(); ctap.reset.side_effect = CtapError(CtapError.ERR.NOT_ALLOWED)
    reconnected = Mock(); reconnected.descriptor = descriptor()
    with patch('fido_manager.backend.Ctap2', return_value=ctap), \
         patch('fido_manager.backend.list_descriptors', side_effect=[[], [descriptor()]]), \
         patch('fido_manager.backend.open_device', return_value=reconnected):
        with pytest.raises(CtapError): hardware.reset(0, Event(), Mock())
    assert ctap.reset.call_count == 1
    reconnected.close.assert_called_once()


def test_pin_setup_and_change_preserve_passkeys_and_clear_session():
    hardware, _ = reset_hardware()
    ctap = Mock(); ctap.info.min_pin_length = 6; ctap.info.max_pin_length = 63
    with patch('fido_manager.backend.Ctap2', return_value=ctap), \
         patch('fido_manager.backend.ClientPin') as client:
        with pytest.raises(ValueError): hardware.set_pin(0, '1234')
        client.assert_not_called()
        hardware.set_pin(0, 'newpin')
        client.return_value.set_pin.assert_called_once_with('newpin')
        hardware.set_pin(0, 'nextpin', 'oldpin')
        client.return_value.change_pin.assert_called_once_with('oldpin', 'nextpin')
    assert hardware.manager is None
    ctap.reset.assert_not_called()


@pytest.mark.parametrize('pin', ['123', 'a'*64, '😀'*16, 'abcd\0'])
def test_pin_validation_enforces_character_and_byte_limits(pin):
    assert validate_pin(pin)


def test_demo_reset_leads_to_pin_setup():
    demo = Demo()
    demo.reset(0, Event(), Mock())
    assert demo.read() == ([], 50)
    assert demo.inspect_key(0).pin_set is False
    demo.set_pin(0, '123456')
    assert demo.inspect_key(0).pin_set is True
    assert demo.read()[0] == []


def test_specific_device_errors_give_specific_next_steps():
    assert 'temporarily' in operation_error(CtapError(CtapError.ERR.PIN_AUTH_BLOCKED))
    assert 'Reset FIDO' in operation_error(CtapError(CtapError.ERR.PIN_BLOCKED))
    assert 'full' in operation_error(CtapError(CtapError.ERR.KEY_STORE_FULL))
    assert 'session expired' in operation_error(CtapError(CtapError.ERR.PIN_TOKEN_EXPIRED))


@pytest.fixture
def app():
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion'); app.setStyleSheet(STYLE)
    return app


@pytest.fixture
def window(app):
    window = Window(demo=True, auto_scan=False)
    window.devices.blockSignals(True); window.devices.addItem('Demo key'); window.devices.blockSignals(False)
    window.key_info = window.backend.info
    window.render()
    yield window
    window.close()


@pytest.mark.parametrize('info,phrase,pin_enabled,reset_enabled', [
    (KeyInfo(pin_set=False), 'Create a PIN', True, True),
    (KeyInfo(retries=0), 'blocked', False, True),
    (KeyInfo(temporarily_blocked=True), 'Unplug', False, True),
    (KeyInfo(force_pin_change=True), 'requires a new PIN', True, True),
    (KeyInfo(fido2=False, pin_set=None, credential_management=False), 'unavailable', False, False),
    (KeyInfo(credential_management=False), 'unavailable', True, True),
])
def test_locked_key_cases_have_recovery_actions(window, info, phrase, pin_enabled, reset_enabled):
    window.key_info = info; window.render()
    assert phrase in window.empty.text()
    assert window.unlock_form.isHidden()
    assert window.pin_btn.isEnabled() is pin_enabled
    assert window.reset_btn.isEnabled() is reset_enabled
    assert not window.empty_action.isHidden()


def test_pin_dialog_requires_current_pin_and_matching_new_values(app):
    dialog = PinDialog(KeyInfo(min_pin_length=6), 'Demo key')
    save = dialog.buttons.button(QDialogButtonBox.StandardButton.Save)
    dialog.new.setText('123456'); dialog.confirm.setText('different')
    assert not save.isEnabled()
    dialog.confirm.setText('123456')
    assert not save.isEnabled()
    dialog.old.setText('oldpin')
    assert save.isEnabled()
    assert dialog.take_values() == ('123456', 'oldpin')
    assert all(not field.text() for field in (dialog.old, dialog.new, dialog.confirm))
    dialog.close()


def test_reset_requires_both_confirmations_and_cancel_stays_open_while_running(app):
    dialog = ResetDialog('Demo key', demo=True)
    start = Mock(); cancel = Mock()
    dialog.start_requested.connect(start); dialog.cancel_requested.connect(cancel)
    dialog.confirm.setText('RESET'); dialog.start()
    start.assert_not_called()
    dialog.ack.setChecked(True); dialog.start_btn.click()
    start.assert_called_once()
    assert dialog.running
    dialog.reject(); cancel.assert_called_once()
    assert dialog.running
    dialog.complete('Cancelled.'); dialog.reject()


def test_demo_reset_workflow_returns_to_setup_state(window, app):
    window.navigate(1)
    # Drive only the demo confirmation dialog. A real reset is never invoked.
    def confirm():
        dialog = window.reset_dialog
        dialog.ack.setChecked(True); dialog.confirm.setText('RESET'); dialog.start_btn.click()
        poll = QTimer(dialog)
        def close_when_done():
            if dialog.finished:
                poll.stop(); dialog.reject()
        poll.timeout.connect(close_when_done); poll.start(10)
    QTimer.singleShot(0, confirm)
    window.reset_key()
    # Wait for the asynchronous rescan and capability inspection.
    from PySide6.QtTest import QTest
    for _ in range(100):
        app.processEvents()
        if not window.busy: break
        QTest.qWait(10)
    assert not window.busy
    assert not window.unlocked
    assert window.rows == []
    assert window.key_info.pin_set is False
    assert window.pin_btn.isEnabled()
    assert 'Reset complete' in window.status.text()


def test_reset_cancellation_during_touch_closes_device_and_never_retries():
    hardware, _ = reset_hardware()
    ctap = Mock(); ctap.reset.side_effect = CtapError(CtapError.ERR.KEEPALIVE_CANCEL)
    reconnected = Mock(); reconnected.descriptor = descriptor()
    with patch('fido_manager.backend.Ctap2', return_value=ctap), \
         patch('fido_manager.backend.list_descriptors', side_effect=[[], [descriptor()]]), \
         patch('fido_manager.backend.open_device', return_value=reconnected):
        with pytest.raises(OperationCancelled, match='not confirmed'):
            hardware.reset(0, Event(), Mock())
    assert ctap.reset.call_count == 1
    reconnected.close.assert_called_once()


def test_no_device_disables_settings_actions(window):
    window.devices.blockSignals(True); window.devices.clear(); window.devices.blockSignals(False)
    window.key_info = None; window.clear()
    assert not window.pin_btn.isEnabled()
    assert not window.reset_btn.isEnabled()
    assert 'Connect' in window.empty.text()


def test_expired_session_clears_passkeys_and_returns_to_unlock(window):
    window.loaded(window.backend.read())
    window.busy = True
    with patch('fido_manager.app.QMessageBox.warning'):
        window.completed((False, CtapError(CtapError.ERR.PIN_TOKEN_EXPIRED)), (Mock(), None))
    assert not window.unlocked
    assert not window.rows
    assert not window.delete_btn.isEnabled()
    assert not window.unlock_form.isHidden()


def test_reset_confirmation_cancel_never_calls_backend(window):
    window.backend.reset = Mock()
    def cancel():
        window.reset_dialog.reject()
    QTimer.singleShot(0, cancel)
    window.reset_key()
    window.backend.reset.assert_not_called()
    assert not window.busy


def test_reset_rechecks_serial_on_open_handle():
    hardware, _ = reset_hardware()
    reconnected = Mock(); reconnected.descriptor = descriptor(serial='replacement')
    with patch('fido_manager.backend.Ctap2') as ctap, \
         patch('fido_manager.backend.list_descriptors', side_effect=[[], [descriptor()]]), \
         patch('fido_manager.backend.open_device', return_value=reconnected):
        with pytest.raises(ValueError, match='changed while opening'):
            hardware.reset(0, Event(), Mock())
    ctap.return_value.reset.assert_not_called()
    reconnected.close.assert_called_once()


@pytest.mark.parametrize('code,retries,blocked', [
    (CtapError.ERR.PIN_BLOCKED, 0, False),
    (CtapError.ERR.PIN_AUTH_BLOCKED, None, True),
])
def test_inspection_keeps_reset_available_when_pin_is_blocked(code, retries, blocked):
    from fido2.ctap2 import Info
    hardware, _ = reset_hardware()
    ctap = Mock(); ctap.info = Info(versions=['FIDO_2_1'], options={'clientPin': True, 'credMgmt': True})
    with patch('fido_manager.backend.Ctap2', return_value=ctap), \
         patch('fido_manager.backend.ClientPin') as client:
        client.return_value.get_pin_retries.side_effect = CtapError(code)
        info = hardware.inspect_key(0)
    assert info.fido2 and info.credential_management
    assert info.retries == retries
    assert info.temporarily_blocked == blocked


def test_unsupported_key_inspection_does_not_attempt_pin_authentication():
    hardware, _ = reset_hardware()
    with patch('fido_manager.backend.Ctap2', side_effect=ValueError('Not a CTAP2 key')), \
         patch('fido_manager.backend.ClientPin') as client:
        info = hardware.inspect_key(0)
    assert not info.fido2 and not info.credential_management and info.pin_set is None
    client.assert_not_called()

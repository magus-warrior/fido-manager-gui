import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from unittest.mock import Mock, patch
from PySide6.QtWidgets import QApplication
from fido_manager.app import Window


def test_connection_changes_rescan_but_busy_operations_are_not_interrupted():
    app = QApplication.instance() or QApplication([])
    window = Window(demo=True, auto_scan=False)
    window.connection_state = (('old', True),)
    window.scan = Mock()
    with patch('fido_manager.app.connection_snapshot', return_value=(('new', True),)):
        window.busy = True
        window.check_connections()
        window.scan.assert_not_called()
        window.busy = False
        window.check_connections()
        window.scan.assert_called_once()
    window.close()


def test_locked_ui_explains_next_step_and_hides_passkey_actions():
    app = QApplication.instance() or QApplication([])
    window = Window(demo=True, auto_scan=False)
    window.devices.blockSignals(True)
    window.devices.addItem('Test key')
    window.devices.blockSignals(False)
    window.key_info = window.backend.info
    window.clear()
    assert 'PIN' in window.empty.text()
    assert window.detail.isHidden()
    assert not window.search.isEnabled()
    assert not window.delete_btn.isEnabled()
    window.loaded(window.backend.read())
    window.controls()
    assert not window.detail.isHidden()
    assert window.search.isEnabled()
    window.close()


def test_inventory_shows_connected_and_disconnected_registration_states():
    from PySide6.QtWidgets import QDialog, QLabel
    app = QApplication.instance() or QApplication([])
    window = Window(demo=True, auto_scan=False)
    window.demo = False
    window.devices.blockSignals(True)
    window.devices.addItem('Test key')
    window.devices.blockSignals(False)
    window.key_info = window.backend.info
    with patch('fido_manager.app.registrations', return_value=([
        {'user': 'alex', 'fingerprint': 'abc123', 'source': '/test/mapping'}], [])), \
         patch('fido_manager.app.inspect_login', return_value=([('kde', 'Screen unlock', True)], '')), \
         patch.object(QDialog, 'exec', return_value=0):
        window.key_inventory()
    text = '\n'.join(widget.text() for widget in window.findChildren(QLabel))
    assert 'Test key — Connected · passkeys locked' in text
    assert 'Registered · connection unknown' in text
    assert 'Key authentication configured · test required' in text
    assert 'Leave the computer password field empty' in text
    window.close()


def test_search_recovery_and_lock_clear_previous_filter():
    app = QApplication.instance() or QApplication([])
    window = Window(demo=True, auto_scan=False)
    window.devices.blockSignals(True)
    window.devices.addItem('Test key')
    window.devices.blockSignals(False)
    window.key_info = window.backend.info
    window.loaded(window.backend.read())
    window.search.setText('no-such-website')
    assert window.list.count() == 0
    assert window.detail.isHidden()
    assert not window.delete_btn.isEnabled()
    assert not window.clear_search_btn.isHidden()
    window.clear_search_btn.click()
    assert window.list.count() == 3
    assert not window.detail.isHidden()
    window.search.setText('github')
    window.clear()
    assert window.search.text() == ''
    window.loaded(window.backend.read())
    assert window.list.count() == 3
    window.close()


def test_selection_survives_refresh_and_full_id_is_available_on_demand():
    app = QApplication.instance() or QApplication([])
    window = Window(demo=True, auto_scan=False)
    window.loaded(window.backend.read())
    window.list.setCurrentRow(1)
    selected_id = window.selected().credential_id
    window.loaded(window.backend.read())
    assert window.selected().credential_id == selected_id
    assert window.credid.isHidden()
    window.technical_btn.click()
    assert not window.credid.isHidden()
    assert window.credid.text().replace(' ', '') == selected_id.hex()
    window.list.setCurrentRow(0)
    assert window.credid.isHidden()
    window.backend.can_edit = False
    window.controls()
    assert not window.edit_btn.isEnabled()
    assert not window.edit_help.isHidden()
    window.close()


def test_scan_selects_key_and_waits_for_inspection_before_unlock():
    from PySide6.QtTest import QTest
    app = QApplication.instance() or QApplication([])
    window = Window(demo=True, auto_scan=False)
    window.scan()
    assert not window.unlock_btn.isEnabled()
    for _ in range(100):
        app.processEvents()
        if not window.busy:
            break
        QTest.qWait(10)
    assert window.devices.currentIndex() == 0
    assert window.key_info is not None
    assert window.unlock_btn.isEnabled()
    assert window.step_labels[1].property('active')
    window.navigate(1)
    window.navigate(0)
    assert window.add_btn.isHidden()
    window.loaded(window.backend.read())
    assert not window.add_btn.isHidden()
    assert window.step_labels[2].property('active')
    window.close()


def test_operation_feedback_is_visible_only_when_there_is_a_message():
    app = QApplication.instance() or QApplication([])
    window = Window(demo=True, auto_scan=False)
    assert window.status.isHidden()
    window.status.setText('Touch your security key to continue.')
    assert not window.status.isHidden()
    window.status.setText('')
    assert window.status.isHidden()
    window.close()

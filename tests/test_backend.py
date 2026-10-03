from unittest.mock import Mock
import pytest
from fido_manager.backend import Hardware, Demo, Credential, CM, LOCAL_RP


def test_empty_key_does_not_enumerate():
    hardware = Hardware()
    hardware.manager = Mock()
    hardware.manager.get_metadata.return_value = {
        CM.RESULT.EXISTING_CRED_COUNT: 0, CM.RESULT.MAX_REMAINING_COUNT: 25}
    assert hardware.read() == ([], 25)
    hardware.manager.enumerate_rps.assert_not_called()


def test_enumerates_and_deletes_only_selected_credential():
    hardware = Hardware()
    manager = hardware.manager = Mock()
    manager.get_metadata.return_value = {
        CM.RESULT.EXISTING_CRED_COUNT: 1, CM.RESULT.MAX_REMAINING_COUNT: 24}
    manager.enumerate_rps.return_value = [{CM.RESULT.RP: {"id": "example.com"}, CM.RESULT.RP_ID_HASH: b'hash'}]
    manager.enumerate_creds.return_value = [{CM.RESULT.USER: {"id": b'user', "name": "alex"},
                                            CM.RESULT.CREDENTIAL_ID: {"id": b'credential'}}]
    rows, _ = hardware.read()
    assert rows[0].rp == 'example.com'
    hardware.delete(rows[0])
    assert manager.delete_cred.call_args.args[0].id == b'credential'


def test_update_keeps_user_and_credential_ids():
    hardware = Hardware()
    manager = hardware.manager = Mock()
    hardware.can_edit = True
    hardware.read = Mock(return_value=([], 10))
    row = Credential('example.com', 'old', 'Old', b'user', b'credential')
    hardware.update(row, 'new', 'New')
    descriptor, user = manager.update_user_info.call_args.args
    assert descriptor.id == b'credential'
    assert user.id == b'user'
    assert user.name == 'new'


def test_locked_and_unsupported_updates_are_rejected():
    hardware = Hardware()
    row = Credential('example.com', 'old', 'Old', b'user', b'credential')
    with pytest.raises(ValueError, match='Unlock'): hardware.delete(row)
    hardware.manager = Mock()
    with pytest.raises(ValueError, match='does not support'): hardware.update(row, 'new', 'New')
    hardware.manager.update_user_info.assert_not_called()


def test_demo_crud_is_isolated():
    demo = Demo()
    original = demo.rows[0]
    rows, _ = demo.create_local('', 'test', 'Test')
    assert len(rows) == 4 and rows[-1].rp == LOCAL_RP
    demo.update(rows[-1], 'changed', 'Changed')
    demo.delete(rows[-1])
    assert len(demo.rows) == 3 and demo.rows[0] is original

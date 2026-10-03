from fido_manager.system_login import inspect


def test_vendor_login_and_local_lock_services(tmp_path):
    local = tmp_path / 'local'
    vendor = tmp_path / 'vendor'
    local.mkdir()
    vendor.mkdir()
    (vendor / 'plasmalogin').write_text('auth substack password-auth\n')
    (local / 'kde').write_text('auth sufficient pam_u2f.so\n')
    services, error = inspect(local, vendor)
    assert not error
    assert ('plasmalogin', 'Plasma login', False) in services
    assert ('kde', 'Plasma screen unlock / resume', True) in services


def test_local_override_and_commented_module(tmp_path):
    local = tmp_path / 'local'
    vendor = tmp_path / 'vendor'
    local.mkdir()
    vendor.mkdir()
    (vendor / 'sddm').write_text('auth sufficient pam_u2f.so\n')
    (local / 'sddm').write_text('# auth sufficient pam_u2f.so\nauth include password-auth\n')
    assert inspect(local, vendor)[0] == [('sddm', 'SDDM login', False)]


def test_unknown_system_has_explicit_limitation(tmp_path):
    assert inspect(tmp_path, tmp_path)[1]


def test_registration_inventory_filters_user_and_hides_material(tmp_path):
    from fido_manager.system_login import registrations
    mapping = tmp_path / 'mapping'
    mapping.write_text('# comment\nalex:handle1,public1:handle2,public2,es256,+presence\nother:secret,public\nalex:handle1,public1\n')
    rows, issues = registrations([mapping], username='alex')
    assert len(rows) == 2
    assert not issues
    assert all(row['user'] == 'alex' and row['source'] == str(mapping) for row in rows)
    assert 'handle1' not in str(rows) and 'public1' not in str(rows)
    assert rows[0]['fingerprint'] != rows[1]['fingerprint']


def test_registration_inventory_handles_missing_and_malformed_files(tmp_path):
    from fido_manager.system_login import registrations
    mapping = tmp_path / 'mapping'
    mapping.write_text('alex:broken:valid,public\n')
    rows, issues = registrations([tmp_path / 'absent', mapping], username='alex')
    assert len(rows) == 1
    assert len(issues) == 1

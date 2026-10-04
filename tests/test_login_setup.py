import importlib.util
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('login_setup', Path(__file__).parents[1] / 'repair-plasma-login.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def test_fresh_configuration_does_not_require_sudo_enrollment():
    line, tokens = helper.configuration('auth include system-auth\n', '', 'alex')
    assert 'auth sufficient pam_u2f.so' in line
    assert 'origin=' + helper.ORIGIN in tokens


def test_existing_configuration_reuses_origin():
    line = 'auth sufficient pam_u2f.so authfile=/etc/u2f_mappings origin=pam://existing'
    assert helper.configuration(line, 'alex:handle,public\n', 'alex')[0] == line


@pytest.mark.parametrize('text', ['auth required pam_u2f.so authfile=/etc/u2f_mappings',
                                 'auth sufficient pam_u2f.so authfile=/etc/u2f_mappings nouserok'])
def test_unsupported_existing_configuration_is_not_overwritten(text):
    with pytest.raises(ValueError):
        helper.configuration(text, '', 'alex')


def test_unknown_existing_registration_origin_is_preserved():
    with pytest.raises(ValueError):
        helper.configuration('', 'alex:handle,public\n', 'alex')


def test_enrollment_runs_as_user_and_uses_matching_origin(monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout='alex:handle,public\n', stderr='')
    monkeypatch.setattr(helper.subprocess, 'run', run)
    assert helper.enroll('alex', ['origin=pam://existing', 'appid=pam://existing']) == 'alex:handle,public\n'
    assert calls[0][0] == ['runuser', '-u', 'alex', '--', 'pamu2fcfg', '-u', 'alex', '-o', 'pam://existing', '-i', 'pam://existing']
    assert calls[0][1]['timeout'] == 90


@pytest.mark.parametrize('output', ['root:handle,public', 'alex:broken', 'alex:handle,public\nother:handle,public'])
def test_invalid_enrollment_does_not_produce_mapping(monkeypatch, output):
    monkeypatch.setattr(helper.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout=output, stderr=''))
    with pytest.raises(ValueError):
        helper.enroll('alex', [])


def test_gdm_selinux_gate_and_password_fallback_preserved():
    text = 'auth required pam_selinux_permit.so\nauth substack password-auth\naccount include password-auth\n'
    result = helper.insert_auth(text, 'auth sufficient pam_u2f.so', 'gdm-password')
    assert result.splitlines()[:3] == ['auth required pam_selinux_permit.so', 'auth sufficient pam_u2f.so', 'auth substack password-auth']
    with pytest.raises(ValueError):
        helper.insert_auth('account include system-auth\n', 'auth sufficient pam_u2f.so', 'unknown')


def test_transaction_rollback_restores_existing_and_removes_new(tmp_path, monkeypatch):
    existing = tmp_path / 'sudo'
    existing.write_text('original\n')
    new = tmp_path / 'mapping'
    monkeypatch.setattr(helper.shutil, 'which', lambda _: None)
    rollback = helper.apply_changes([(existing, 'changed\n'), (new, 'alex:handle,public\n')], tmp_path)
    subprocess.run(['sh', str(rollback)], check=True)
    assert existing.read_text() == 'original\n'
    assert not new.exists()


def test_write_failure_rolls_back(tmp_path, monkeypatch):
    target = tmp_path / 'sudo'
    target.write_text('original\n')
    monkeypatch.setattr(helper.shutil, 'which', lambda _: None)
    replace = helper.os.replace
    def fail_on_second(source, dest):
        if Path(dest).name == 'mapping':
            raise OSError('simulated failure')
        replace(source, dest)
    monkeypatch.setattr(helper.os, 'replace', fail_on_second)
    with pytest.raises(OSError):
        helper.apply_changes([(target, 'changed\n'), (tmp_path / 'mapping', 'registration')], tmp_path)
    assert target.read_text() == 'original\n'

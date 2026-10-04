"""Installer integrations without touching the user's desktop or hardware."""
import importlib.util
from pathlib import Path
import plistlib
import subprocess

spec = importlib.util.spec_from_file_location('installer', Path(__file__).parents[1] / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def test_linux_launcher_runs_from_other_directory(tmp_path, monkeypatch):
    home = tmp_path / 'home with spaces'
    root = home / 'app'
    root.mkdir(parents=True)
    data = home / 'custom-data'
    monkeypatch.setenv('XDG_DATA_HOME', str(data))
    python = root / 'fake-python'
    installer.write_executable(python, '#!/bin/sh\nprintf "%s\\n" "$PWD" "$@"\n')
    desktop = installer.create_launcher('linux', home, root, python)
    assert desktop == data / 'applications/fido-manager.desktop'
    assert 'Terminal=false' in desktop.read_text()
    result = subprocess.run([str(home / '.local/bin/fido-manager'), '--demo'], cwd=tmp_path,
                            check=True, capture_output=True, text=True)
    assert result.stdout.splitlines() == [str(root), '-m', 'fido_manager', '--demo']


def test_macos_bundle(tmp_path):
    bundle = installer.create_launcher('darwin', tmp_path, tmp_path / 'app', tmp_path / 'venv/bin/python')
    with (bundle / 'Contents/Info.plist').open('rb') as stream:
        info = plistlib.load(stream)
    assert info['CFBundleExecutable'] == 'fido-manager'
    assert (bundle / 'Contents/MacOS/fido-manager').stat().st_mode & 0o111


def test_windows_start_menu(tmp_path, monkeypatch):
    monkeypatch.setenv('APPDATA', str(tmp_path / 'Roaming'))
    calls = []
    monkeypatch.setattr(installer.subprocess, 'run', lambda *args, **kwargs: calls.append((args, kwargs)))
    shortcut = installer.create_launcher('win32', tmp_path, tmp_path / "user's app", tmp_path / 'venv/Scripts/python.exe')
    assert shortcut.name == 'FIDO Manager.lnk'
    script = calls[0][0][0][-1]
    assert 'pythonw.exe' in script
    assert "user''s app" in script
    assert "-m fido_manager" in script
    assert calls[0][1]['check']


def test_desktop_quoting():
    assert installer.desktop_quote('/home/a b/100%/run') == '"/home/a b/100%%/run"'


def test_installer_enrollment_passes_user_and_flag(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(installer.getpass, 'getuser', lambda: 'alex')
    monkeypatch.setattr(installer.subprocess, 'run', lambda command, **kwargs: calls.append((command, kwargs)))
    installer.setup_login(tmp_path)
    assert calls == [(['sudo', '/usr/bin/python3', str(tmp_path / 'repair-plasma-login.py'), '--user', 'alex', '--enroll'], {'check': True})]

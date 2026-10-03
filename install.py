#!/usr/bin/env python3
"""Install FIDO Manager for the current user, without administrator privileges."""
import argparse
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys
import venv

NAME = 'FIDO Manager'
SOURCE = Path(__file__).resolve().parent


def install_root(platform, home):
    if platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', home / 'AppData/Local')) / 'FIDO Manager'
    if platform == 'darwin':
        return home / 'Library/Application Support/FIDO Manager'
    return Path(os.environ.get('XDG_DATA_HOME', home / '.local/share')) / 'fido-manager'


def write_executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    path.chmod(0o755)


def desktop_quote(value):
    # Desktop Entry Exec quoting is distinct from shell quoting.
    value = str(value).replace('%', '%%')
    for char in ('\\', '"', '`', '$'):
        value = value.replace(char, '\\' + char)
    return '"' + value.replace('\\', '\\\\') + '"'


def create_launcher(platform, home, root, python):
    if platform == 'win32':
        shortcut = Path(os.environ.get('APPDATA', home / 'AppData/Roaming')) / 'Microsoft/Windows/Start Menu/Programs/FIDO Manager.lnk'
        shortcut.parent.mkdir(parents=True, exist_ok=True)
        def ps(value):
            return "'" + str(value).replace("'", "''") + "'"
        script = (
            '$w = New-Object -ComObject WScript.Shell; '
            f'$s = $w.CreateShortcut({ps(shortcut)}); '
            f'$s.TargetPath = {ps(python.with_name("pythonw.exe"))}; '
            "$s.Arguments = '-m fido_manager'; "
            f'$s.WorkingDirectory = {ps(root)}; '
            f'$s.Description = {ps(NAME)}; $s.Save()'
        )
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script], check=True)
        return shortcut
    script = '#!/bin/sh\ncd ' + shlex.quote(str(root)) + ' || exit 1\nexec ' + shlex.quote(str(python)) + ' -m fido_manager "$@"\n'
    if platform == 'darwin':
        bundle = home / 'Applications/FIDO Manager.app'
        write_executable(bundle / 'Contents/MacOS/fido-manager', script)
        with (bundle / 'Contents/Info.plist').open('wb') as stream:
            plistlib.dump({'CFBundleName': NAME, 'CFBundleDisplayName': NAME,
                          'CFBundleIdentifier': 'io.github.magus-warrior.fido-manager',
                          'CFBundleExecutable': 'fido-manager', 'CFBundlePackageType': 'APPL',
                          'CFBundleVersion': '1', 'NSHighResolutionCapable': True}, stream)
        return bundle
    launcher = home / '.local/bin/fido-manager'
    write_executable(launcher, script)
    desktop = Path(os.environ.get('XDG_DATA_HOME', home / '.local/share')) / 'applications/fido-manager.desktop'
    desktop.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text('[Desktop Entry]\nType=Application\nName=FIDO Manager\n'
                       'Comment=Manage FIDO2 security keys and passkeys\n'
                       f'Exec={desktop_quote(launcher)}\nIcon=dialog-password\n'
                       'Terminal=false\nCategories=Utility;Security;\nStartupNotify=true\n', encoding='utf-8')
    return desktop


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    if sys.version_info < (3, 10):
        parser.error('Python 3.10 or newer is required.')
    if sys.platform not in ('linux', 'darwin', 'win32'):
        parser.error('Supported platforms: Linux, macOS, Windows.')
    if hasattr(os, 'geteuid') and os.geteuid() == 0:
        parser.error('Run as your desktop user, without sudo.')
    home = Path.home()
    root = install_root(sys.platform, home)
    root.mkdir(parents=True, exist_ok=True)
    environment = root / 'venv'
    python = environment / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    print(f'Installing into {root}', flush=True)
    try:
        if not python.exists():
            venv.EnvBuilder(with_pip=True).create(environment)
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(SOURCE / 'requirements.txt')], check=True)
        shutil.copytree(SOURCE / 'fido_manager', root / 'fido_manager', dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copy2(SOURCE / 'repair-plasma-login.py', root)
        launcher = create_launcher(sys.platform, home, root, python)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f'Installation failed: {exc}\nCheck internet access and Python venv/pip support. '
              'On Debian/Ubuntu install python3-venv, then rerun this installer.', file=sys.stderr)
        return 1
    print(f'Installed. Open {NAME} from your application menu.\nLauncher: {launcher}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

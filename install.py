#!/usr/bin/env python3
"""Install FIDO Manager for the current user, without administrator privileges."""
import argparse
import getpass
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


def fedora_dependencies():
    release = Path('/etc/os-release')
    if sys.platform != 'linux' or not release.exists():
        return
    if not any(line in ('ID=fedora', 'ID="fedora"') for line in release.read_text().splitlines()):
        return
    if Path('/run/ostree-booted').exists():
        raise OSError('Fedora Atomic: install pam-u2f, pamu2fcfg and polkit with rpm-ostree, reboot, then rerun with --skip-system-packages.')
    print('Installing Fedora desktop and security-key dependencies (administrator password may be requested).', flush=True)
    subprocess.run(['sudo', 'dnf', 'install', '-y', 'pam-u2f', 'pamu2fcfg', 'polkit',
                    'libxkbcommon-x11', 'xcb-util-cursor'], check=True)


def setup_login(root):
    subprocess.run(['sudo', '/usr/bin/python3', str(root / 'repair-plasma-login.py'),
                    '--user', getpass.getuser(), '--enroll'], check=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-system-packages', action='store_true', help='Skip Fedora host dependency installation')
    login = parser.add_mutually_exclusive_group()
    login.add_argument('--setup-login', action='store_true', help='Enroll a key and configure Linux computer login')
    login.add_argument('--skip-login', action='store_true', help='Install the app without offering computer-login setup')
    args = parser.parse_args(argv)
    if args.setup_login and sys.platform != 'linux':
        parser.error('Computer-login enrollment is currently supported on Linux only.')
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
        if not args.skip_system_packages:
            fedora_dependencies()
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
    if sys.platform == 'linux' and not args.skip_login:
        requested = args.setup_login
        if not requested and sys.stdin.isatty():
            print('Computer login setup registers your key, enables key OR password login, and backs up changed files.')
            requested = input('Set up computer login now? Connect one key and be ready to touch it. [Y/n] ').strip().lower() in ('', 'y', 'yes')
        if requested:
            try:
                setup_login(root)
            except (OSError, subprocess.CalledProcessError) as exc:
                print(f'The app is installed, but computer-login setup did not finish: {exc}\nRetry using Computer login → Configure computer login in the app.', file=sys.stderr)
                return 1
        else:
            print('Computer-login setup deferred. You can enroll later from Computer login in the app.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

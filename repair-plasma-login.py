#!/usr/bin/env python3
"""Enroll a login key and configure detected Linux PAM services."""
import argparse
import os
from pathlib import Path
import pwd
import shlex
import shutil
import subprocess
import tempfile
from fido_manager.system_login import inspect

ORIGIN = 'pam://fido-manager-local-login'


def install_dependencies():
    if shutil.which('pamu2fcfg'):
        return
    release = Path('/etc/os-release').read_text()
    if not any(line in ('ID=fedora', 'ID="fedora"') for line in release.splitlines()):
        raise ValueError('Install pam-u2f and pamu2fcfg with your distribution package manager, then retry.')
    if Path('/run/ostree-booted').exists():
        raise ValueError('Fedora Atomic requires pam-u2f and pamu2fcfg in the host deployment. Install them with rpm-ostree and reboot, then retry.')
    subprocess.run(['dnf', 'install', '-y', 'pam-u2f', 'pamu2fcfg'], check=True)


def configuration(sudo_text, mapping_text, user):
    candidates = [line for line in sudo_text.splitlines()
                  if line.strip() and not line.lstrip().startswith('#') and 'pam_u2f.so' in line]
    if candidates:
        tokens = shlex.split(candidates[0])
        if (len(candidates) != 1 or tokens[:3] != ['auth', 'sufficient', 'pam_u2f.so']
                or 'authfile=/etc/u2f_mappings' not in tokens
                or any(t.split('=')[0] in ('nouserok', 'alwaysok') for t in tokens)):
            raise ValueError('Existing sudo key configuration needs manual review; nothing changed.')
        return candidates[0], tokens
    if mapping_text.strip():
        raise ValueError('Existing /etc/u2f_mappings has no matching sudo configuration. Its enrollment settings must be identified before setup; nothing changed.')
    line = f'auth sufficient pam_u2f.so authfile=/etc/u2f_mappings cue origin={ORIGIN} appid={ORIGIN}'
    return line, shlex.split(line)


def enroll(user, tokens):
    # Run as the desktop user: the privileged helper never chooses a root identity.
    command = ['runuser', '-u', user, '--', 'pamu2fcfg', '-u', user]
    for option, flag in [('origin', '-o'), ('appid', '-i')]:
        value = next((t.split('=', 1)[1] for t in tokens if t.startswith(option + '=')), None)
        if value:
            command.extend([flag, value])
    print('Touch your security key to register it for computer login (90-second timeout).', flush=True)
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise ValueError('Key enrollment failed: ' + (result.stderr.strip() or 'Check that one key is connected and touch it when it flashes.'))
    record = result.stdout.strip()
    fields = record.split(':')
    if '\n' in record or len(fields) != 2 or fields[0] != user or len(fields[1].split(',')) < 2:
        raise ValueError('Enrollment returned an invalid registration; nothing changed.')
    return record + '\n'


def insert_auth(content, pam_line, service):
    if 'pam_u2f.so' in content:
        raise ValueError(f'{service} already has key configuration; review it manually.')
    rows = content.splitlines(keepends=True)
    position = next((i for i, row in enumerate(rows)
                     if row.split() and row.split()[0] == 'auth'
                     and 'pam_selinux_permit.so' not in row), None)
    if position is None:
        raise ValueError(f'{service}: no supported authentication stack; nothing changed.')
    rows.insert(position, pam_line + '\n')
    return ''.join(rows)


def apply_changes(changes, backup_root=Path('/root')):
    backup = Path(tempfile.mkdtemp(prefix='fido-login-backup-', dir=backup_root))
    restore = ['#!/bin/sh', 'set -eu']
    for index, (target, _) in enumerate(changes):
        if target.is_symlink():
            raise ValueError(f'Refusing to replace symlink {target}; nothing changed.')
        saved = backup / str(index)
        if target.exists():
            shutil.copy2(target, saved)
            restore.append(f'cp -p {shlex.quote(str(saved))} {shlex.quote(str(target))}')
        else:
            restore.append(f'rm -f {shlex.quote(str(target))}')
        if shutil.which('restorecon'):
            restore.append(f'if test -f {shlex.quote(str(target))}; then restorecon {shlex.quote(str(target))}; fi')
    rollback = backup / 'restore.sh'
    rollback.write_text('\n'.join(restore) + '\n')
    rollback.chmod(0o700)
    try:
        for target, content in changes:
            fd, name = tempfile.mkstemp(prefix='.fido-', dir=target.parent)
            try:
                with os.fdopen(fd, 'w') as stream:
                    stream.write(content)
                os.chmod(name, 0o644)
                os.replace(name, target)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
        if shutil.which('restorecon'):
            subprocess.run(['restorecon', *(str(t) for t, _ in changes)], check=True)
    except Exception:
        subprocess.run(['sh', str(rollback)], check=True)
        raise
    return rollback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user', required=True)
    parser.add_argument('--enroll', action='store_true', help='Enroll this user if no central registration exists')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Administrator authentication is required.')
    account = pwd.getpwnam(args.user)
    if account.pw_uid == 0 or any(c in args.user for c in ':\n\r'):
        parser.error('Choose a non-root desktop user.')
    invoking_uid = os.environ.get('PKEXEC_UID') or os.environ.get('SUDO_UID')
    if invoking_uid is None or int(invoking_uid) != account.pw_uid:
        parser.error('The target user must match the user requesting administrator authentication.')
    mapping = Path('/etc/u2f_mappings')
    mapping_text = mapping.read_text() if mapping.exists() else ''
    sudo = Path('/etc/pam.d/sudo')
    pam_line, tokens = configuration(sudo.read_text() if sudo.exists() else '', mapping_text, args.user)
    changes = []
    services, error = inspect()
    if error:
        raise ValueError(error)
    for service, _, enabled in services:
        if enabled:
            continue
        target = Path('/etc/pam.d') / service
        source = target if target.exists() else Path('/usr/lib/pam.d') / service
        changes.append((target, insert_auth(source.read_text(), pam_line, service)))
    if sudo.exists() and not any('pam_u2f.so' in line and not line.lstrip().startswith('#') for line in sudo.read_text().splitlines()):
        changes.append((sudo, insert_auth(sudo.read_text(), pam_line, 'sudo')))
    enrolled = any(line.startswith(args.user + ':') and ',' in line for line in mapping_text.splitlines())
    if not enrolled:
        if not args.enroll:
            raise ValueError('No existing registration. Run setup with enrollment enabled.')
        if any(line.startswith(args.user + ':') for line in mapping_text.splitlines()):
            raise ValueError('Existing registration is malformed; review /etc/u2f_mappings before enrolling again.')
        install_dependencies()
        mapping_text = mapping_text.rstrip('\n') + ('\n' if mapping_text else '') + enroll(args.user, tokens)
    if not changes and enrolled:
        print('Detected login services already have key authentication configured. Test login with your key.')
        return
    changes.insert(0, (mapping, mapping_text))
    rollback = apply_changes(changes)
    print('Computer-login setup complete. Password fallback remains available.')
    print(f'Rollback: sudo sh {rollback}')
    print('Test screen unlock with your key before logging out. GNOME Keyring may still require your password.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f'Computer-login setup failed: {exc}')

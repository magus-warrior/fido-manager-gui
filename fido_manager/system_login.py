"""Read-only inspection of Linux PAM login integration."""
from pathlib import Path
import sys

SERVICES = {"plasmalogin": "Plasma login", "sddm": "SDDM login",
            "gdm-password": "GNOME login", "lightdm": "LightDM login",
            "kde": "Plasma screen unlock / resume", "login": "Console login"}


def inspect(pam_root=Path('/etc/pam.d'), vendor_root=Path('/usr/lib/pam.d')):
    if sys.platform != 'linux':
        return [], 'Computer login setup requires Linux with PAM.'
    found = []
    for service, label in SERVICES.items():
        path = pam_root / service
        if not path.exists():
            path = vendor_root / service
        if path.is_file():
            enabled = any('pam_u2f.so' in line and not line.lstrip().startswith('#')
                          for line in path.read_text().splitlines())
            found.append((service, label, enabled))
    return found, '' if found else 'No supported PAM login services found.'


def registrations(mapping_paths=None, username=None):
    """List public PAM registrations without exposing credential material.

    Registrations have no device serial or presence status: do not match them to
    connected hardware or claim that a configured registration works.
    """
    import getpass
    import hashlib
    import shlex
    username = username or getpass.getuser()
    if mapping_paths is None:
        paths = {Path('/etc/u2f_mappings'), Path.home() / '.config/Yubico/u2f_keys'}
        for root in (Path('/etc/pam.d'), Path('/usr/lib/pam.d')):
            for service in (*SERVICES, 'sudo'):
                try:
                    lines = (root / service).read_text().splitlines()
                except OSError:
                    continue
                for line in lines:
                    if line.lstrip().startswith('#') or 'pam_u2f.so' not in line:
                        continue
                    try:
                        for token in shlex.split(line, comments=True):
                            if token.startswith('authfile='):
                                value = token.split('=', 1)[1]
                                if value.startswith('/'):
                                    paths.add(Path(value))
                    except ValueError:
                        continue
        mapping_paths = sorted(paths)
    rows, issues = [], []
    seen = set()
    for path in mapping_paths:
        path = Path(path)
        try:
            lines = path.read_text().splitlines()
        except FileNotFoundError:
            continue
        except OSError:
            issues.append(f'{path}: cannot read registrations')
            continue
        for line in lines:
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            parts = line.strip().split(':')
            if parts[0] != username:
                continue
            for entry in parts[1:]:
                fields = entry.split(',')
                if len(fields) < 2 or not all(fields[:2]):
                    issues.append(f'{path}: incomplete registration for {username}')
                    continue
                fingerprint = hashlib.sha256(fields[0].encode()).hexdigest()[:12]
                identity = (str(path), fingerprint)
                if identity in seen:
                    continue
                seen.add(identity)
                rows.append({'user': username, 'fingerprint': fingerprint, 'source': str(path)})
    return rows, issues

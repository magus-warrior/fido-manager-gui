#!/usr/bin/env python3
"""Enable the existing enrolled key for Plasma login and screen unlock."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from fido_manager.system_login import inspect


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo python3 repair-plasma-login.py")
    mapping = Path("/etc/u2f_mappings")
    user = os.environ.get("SUDO_USER", "magus")
    if not mapping.is_file() or not any(
        line.startswith(user + ":") for line in mapping.read_text().splitlines()
    ):
        raise SystemExit("No existing key registration for this user; nothing changed.")
    # Reuse the parameters of the working sudo configuration.
    lines = Path("/etc/pam.d/sudo").read_text().splitlines()
    candidates = [line for line in lines if line.startswith("auth sufficient pam_u2f.so ")]
    if len(candidates) != 1 or "authfile=/etc/u2f_mappings" not in candidates[0]:
        raise SystemExit("Unexpected sudo key configuration; nothing changed.")
    pam_line = candidates[0]
    changes = []
    services, error = inspect()
    if error:
        raise SystemExit(error)
    for service, _, enabled in services:
        if enabled:
            continue
        target = Path("/etc/pam.d") / service
        source = target if target.exists() else Path("/usr/lib/pam.d") / service
        content = source.read_text()
        if "pam_u2f.so" in content:
            raise SystemExit(f"{service} already has key configuration; review it manually.")
        rows = content.splitlines(keepends=True)
        # Keep the login manager's SELinux gate ahead of the authentication methods.
        position = next(i for i, row in enumerate(rows)
                        if row.split() and row.split()[0] == "auth"
                        and "pam_selinux_permit.so" not in row)
        rows.insert(position, pam_line + "\n")
        changes.append((target, "".join(rows)))
    if not changes:
        print("Detected login services already have key authentication configured.")
        return
    backup = Path(tempfile.mkdtemp(prefix="fido-plasma-backup-", dir="/root"))
    shutil.copy2(mapping, backup / mapping.name)
    restore = ["#!/bin/sh", "set -eu"]
    for target, _ in changes:
        if target.exists():
            shutil.copy2(target, backup / target.name)
            restore.append(f"cp -p '{backup / target.name}' '{target}'")
        else:
            restore.append(f"rm -f '{target}'")
    restore.extend([f"cp -p '{backup / mapping.name}' '{mapping}'",
                    "restorecon /etc/u2f_mappings"])
    for target, _ in changes:
        restore.append(f"if test -f '{target}'; then restorecon '{target}'; fi")
    rollback = backup / "restore.sh"
    rollback.write_text("\n".join(restore) + "\n")
    rollback.chmod(0o700)
    try:
        # Plasma's screen locker runs as the desktop user. The mapping contains
        # public registration data and stays writable only by root.
        mapping.chmod(0o644)
        for target, content in changes:
            fd, name = tempfile.mkstemp(prefix=".fido-", dir=target.parent)
            try:
                with os.fdopen(fd, "w") as stream:
                    stream.write(content)
                os.chmod(name, 0o644)
                os.replace(name, target)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
        subprocess.run(["restorecon", str(mapping), *(str(t) for t, _ in changes)], check=True)
    except Exception:
        subprocess.run(["sh", str(rollback)], check=True)
        raise
    print("Enabled key authentication for: " + ", ".join(t.name for t, _ in changes))
    print("Password fallback remains available. No restart needed.")
    print(f"Rollback: sudo sh {rollback}")
    print("Test by locking the screen, starting authentication, and touching the key.")


if __name__ == "__main__":
    main()

# FIDO Manager

A Python desktop workspace for FIDO2 security keys, with a light PySide6 interface and separate passkey, key settings, and computer-login views. Supports multiple connected keys, PIN setup/change, credential search, account name edits when supported, confirmed deletion, and guided FIDO reset. No PIN or credentials are saved to disk.

UI previews: [Saved passkeys](docs/saved-passkeys.png) · [Key settings](docs/key-settings.png) · [Reset confirmation](docs/reset-confirmation.png).

## Install (Linux, Windows, macOS)

Install Python 3.10 or newer with pip, download or clone this repository, and run
its installer as your normal desktop user:

- **Linux:** run `./install.sh`. On Debian/Ubuntu, install `python3-venv` first if
  it is missing. Launch **FIDO Manager** from your desktop application menu, or
  run `~/.local/bin/fido-manager` (add `~/.local/bin` to PATH to use the short name).
- **Windows:** double-click `install.bat`, or run `py -3 install.py` in a terminal.
  Launch **FIDO Manager** from the Start menu.
- **macOS:** run `./install.sh`, then open `~/Applications/FIDO Manager.app`.

On standard Fedora, the installer also installs `pam-u2f`, `pamu2fcfg`, polkit,
and Qt desktop libraries through an administrator prompt. It then offers to
register your key and configure computer login. Connect one key and touch it
when it flashes. Use `./install.sh --setup-login` to request enrollment directly,
`--skip-login` to defer it, or `--skip-system-packages` when host dependencies
are already managed separately. Fedora Atomic requires host package layering
and a reboot before running with `--skip-system-packages`. Noninteractive
installs defer enrollment unless `--setup-login` is supplied.

The installer creates a private virtual environment, installs the pinned
requirements, copies the application, and creates a launcher. Internet access is
required for dependencies. You can move or delete the downloaded repository after
installation. Close the app and rerun the installer from an updated checkout to
upgrade. The app installs per user; system packages and computer-login setup
require administrator authentication. This adds a menu launcher; it
does not automatically start the app at login.

Installation locations are `$XDG_DATA_HOME/fido-manager` (default
`~/.local/share/fido-manager`) on Linux, `%LOCALAPPDATA%\FIDO Manager` on Windows,
and `~/Library/Application Support/FIDO Manager` on macOS. To uninstall, delete
that directory and its launcher: Linux `~/.local/bin/fido-manager` and
`$XDG_DATA_HOME/applications/fido-manager.desktop` (default
`~/.local/share/applications/fido-manager.desktop`); Windows
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\FIDO Manager.lnk`; macOS
`~/Applications/FIDO Manager.app`.

Platform dependency wheels must be available for your Python version and CPU.
Linux still requires a working graphical desktop and distribution-provided Qt
runtime libraries and security-key udev permissions. Computer-login configuration
is Linux-only. Windows/macOS launcher generation is covered by automated tests;
installation and hardware access on those systems require native verification.

## Run from the checkout

After installing the dependencies, launch the app with:

```sh
./run.sh
```

For a fresh installation (Python 3.10+):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./run.sh
```

Use `./run.sh --demo` for an isolated in-memory preview with working create, read, update, and delete flows. Demo mode never opens hardware.

## Using your key

Plug in your key; on Linux the app watches USB connection and access changes automatically. Select your device if more than one is connected, enter its existing FIDO2 PIN (not your computer password), and click **Unlock passkeys**. **Reload passkeys** lists discoverable (resident) credentials. Editing changes names stored on the key, not the website account. Delete requires explicit confirmation and permanently removes the selected credential.

The three-step guide shows whether to connect, unlock, or manage your key. Operation feedback appears below the key selector.

The saved-passkeys view keeps website and account names in the list, with actions in the details panel. Use **Show credential ID** for the full identifier or **Missing a passkey?** to check what this list can show. Search includes display names; locking or switching keys clears the filter.

**Add a website…** opens a website's HTTPS security settings so you can complete registration there. The local test option creates a real discoverable credential scoped to `fido-manager.localhost`, requests your PIN again, and waits up to 45 seconds for a touch. It is only for trying the device and does not provide website login. Remove it when finished.

Non-discoverable FIDO/U2F credentials cannot be enumerated. Some devices do not implement credential management or name updates; the app checks capabilities. **Key settings** remains available while passkeys are locked, including on keys that support FIDO2 but cannot list credentials.

## PIN and reset

Open **Key settings** to set a first PIN or change an existing one. The app checks the key's minimum PIN length, the UTF-8 byte limit, and confirmation. Changing a PIN keeps the passkeys and locks the current session. Incorrect PINs, temporary blocks, permanent blocks, required PIN changes, expired sessions, and full storage have specific recovery messages.

**Reset this key…** resets its FIDO application. It removes the FIDO PIN and saved passkeys and invalidates FIDO credentials, including older U2F and computer-login registrations. You must register the key again with each service afterward. This does not configure or reset other applications on a multi-purpose key.

The dialog requires acknowledging another way to sign in and typing `RESET`. Then unplug all security keys, reconnect only the selected key, and touch it when prompted. The app sends the reset request immediately after reconnection because devices allow only a short reset window. It checks the device model and serial when available, rejects multiple or mismatched keys, and never retries reset automatically. Keys without serial numbers cannot be distinguished from another identical model; reconnect only the intended physical key.

Reconnect has a 60-second timeout and touch has a 30-second timeout. Cancellation waits for the device response; it cannot undo a completed reset. If reset is not confirmed, reconnect and inspect the key before retrying. After success, the app rescans and offers PIN setup. Demo mode simulates this flow in memory without accessing hardware. U2F-only and vendor-restricted devices may require the manufacturer's tool.

Protocol references: [FIDO authenticator reset](https://fidoalliance.org/specs/fido-v2.2-rd-20241003/fido-client-to-authenticator-protocol-v2.2-rd-20241003.html#authenticatorReset), [Yubico reset timing and touch requirements](https://docs.yubico.com/yesdk/users-manual/application-fido2/fido2-reset.html).

If no key appears on Linux, the app checks for inaccessible FIDO hidraw interfaces and provides permission guidance. Check FIDO hidraw access using your distribution's security-key/udev setup. Run as your ordinary desktop user. A USB connection change clears the session and rescans; unlock again after reconnecting. On other platforms use **Find keys**. Lock session clears the UI and releases authentication references; device handles close on rescan or exit.

## Computer login and unlocking after suspend

Use **Computer login…** in the sidebar to see connected keys (locked or unlocked),
readable PAM registrations for your user, and login service configuration. Registered
keys remain listed when unplugged; PAM mappings cannot identify their physical device
or connection status. Unregistered devices have no saved connection history.

At computer login, leave the password empty, press Enter or Sign in, then touch
the key when prompted. The FIDO2 PIN in this app is for managing passkeys.

Use **Configure computer login…** inside **Computer login…** to inspect installed Linux PAM
services. The app detects Plasma Login Manager, SDDM, GDM, LightDM, Plasma
screen unlock, and console login, including vendor configurations in
`/usr/lib/pam.d`. A detected PAM module is not proof of working authentication;
test login and screen unlock with your key after setup.

Setup reuses an existing compatible central registration or enrolls your first
key for computer login. Fresh Fedora systems no longer require a preconfigured
`sudo` registration. The setup installs missing Fedora enrollment tools, asks you
to touch the key, and configures detected login services plus `sudo` with password
fallback. Enrollment has a 90-second timeout. Existing registrations with unknown
settings and unsupported PAM configurations are left for manual review.
FIDO2 passkey management remains separate from operating-system login.
Other operating systems are not covered by computer-login setup.

Setup uses polkit's `pkexec` administrator prompt, backs up changed files under
`/root`, prints a rollback command, and preserves password fallback. It makes the
central public registration mapping readable for the user-run Plasma locker while
keeping it writable only by root. Existing PAM key configurations are skipped.
Computer-login setup does not reset your key or remove saved passkeys.
GNOME Keyring may still request your account password after key-based login. No display-manager restart is needed.

## Validation

```sh
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest -q
```

Tests cover CRUD, PIN validation and updates, key capability states, reset confirmation, reconnect identity checks, cancellation, timeouts, session expiry, and the demo reset-to-setup flow. Reset and PIN writes were verified with mocks and demo data, not physical hardware. No real key was reset during development. Real reset requires the in-app confirmation and physical touch; PIN changes require the current PIN.

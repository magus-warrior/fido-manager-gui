"""Hardware access. No PIN or credential material is written to disk."""
from dataclasses import dataclass
from threading import Event, Timer
import hashlib
import os
import time
from pathlib import Path


def connection_snapshot():
    """Read Linux connection metadata without opening or authenticating a key."""
    if not sys_platform_linux():
        return None
    return tuple(sorted((str(p), os.access(p, os.R_OK | os.W_OK))
                        for p in Path('/dev').glob('hidraw*')))


def sys_platform_linux():
    import sys
    return sys.platform.startswith('linux')


def detection_help():
    if sys_platform_linux():
        from fido2.hid.base import parse_report_descriptor
        for node in Path('/sys/class/hidraw').glob('hidraw*'):
            try:
                parse_report_descriptor((node / 'device/report_descriptor').read_bytes())
            except (OSError, ValueError):
                continue
            if not os.access('/dev/' + node.name, os.R_OK | os.W_OK):
                return ('A security key is connected, but your user cannot access it. '
                        'Enable your distribution’s FIDO security-key udev permissions, '
                        'then unplug and reconnect the key.')
    return 'Plug in your security key. It will appear automatically. If it stays missing, try another USB port and click Rescan.'

from fido2.hid import CtapHidDevice, list_descriptors, open_device
from fido2.ctap import CtapError
from fido2.ctap2 import Ctap2
from fido2.ctap2.pin import ClientPin
from fido2.ctap2.credman import CredentialManagement as CM
from fido2.webauthn import PublicKeyCredentialDescriptor, PublicKeyCredentialUserEntity

LOCAL_RP = "fido-manager.localhost"


@dataclass
class KeyInfo:
    fido2: bool = True
    pin_set: bool | None = True
    credential_management: bool = True
    min_pin_length: int = 4
    max_pin_length: int = 63
    force_pin_change: bool = False
    retries: int | None = None
    temporarily_blocked: bool = False
    serial: str | None = None


class OperationCancelled(Exception):
    pass


def validate_pin(pin, minimum=4, maximum=63):
    if len(pin) < minimum:
        return f"Use at least {minimum} characters."
    if len(pin.encode('utf-8')) > maximum:
        return f"Use at most {maximum} UTF-8 bytes (some characters use more than one)."
    if '\0' in pin:
        return "The PIN cannot contain a null character."
    return ""


def operation_error(error):
    """Translate device failures into a next step without suggesting PIN retries blindly."""
    if isinstance(error, OperationCancelled):
        return str(error) or "Operation cancelled."
    if isinstance(error, CtapError):
        messages = {
            CtapError.ERR.PIN_INVALID: "Incorrect PIN. Check it before trying again; repeated failures block the key.",
            CtapError.ERR.PIN_AUTH_BLOCKED: "PIN temporarily blocked. Unplug and reconnect the key before trying again.",
            CtapError.ERR.PIN_BLOCKED: "PIN blocked. Reset FIDO in Key settings to use this key again. Reset invalidates its existing FIDO sign-ins.",
            CtapError.ERR.PIN_NOT_SET: "No PIN is set. Open Key settings to create one.",
            CtapError.ERR.PIN_POLICY_VIOLATION: "This PIN does not meet the key’s policy. Choose a longer PIN that meets your organization’s requirements.",
            CtapError.ERR.PIN_TOKEN_EXPIRED: "Your session expired. Lock the session, then unlock again with your PIN.",
            CtapError.ERR.PIN_AUTH_INVALID: "The key no longer accepts this session. Lock it, then unlock again.",
            CtapError.ERR.PUAT_REQUIRED: "The key requires authentication again. Unlock it with your PIN.",
            CtapError.ERR.KEY_STORE_FULL: "The key is full. Remove a passkey you no longer use before adding another.",
            CtapError.ERR.USER_ACTION_TIMEOUT: "The key timed out waiting for a touch. Try again and touch it when prompted.",
            CtapError.ERR.ACTION_TIMEOUT: "The key timed out. Try again and touch it when prompted.",
            CtapError.ERR.TIMEOUT: "The key timed out. Reconnect it and try the operation again.",
            CtapError.ERR.KEEPALIVE_CANCEL: "The request was cancelled. No successful result was received.",
            CtapError.ERR.NOT_ALLOWED: "The key refused this operation. For a reset, start again and reconnect the key when prompted.",
            CtapError.ERR.OPERATION_DENIED: "The key denied the request. Check its touch or reset requirements and try again.",
            CtapError.ERR.INVALID_COMMAND: "This key does not support this operation. Check the manufacturer’s management tool.",
            CtapError.ERR.CHANNEL_BUSY: "The key is busy. Close other apps using it, then try again.",
        }
        return messages.get(error.code, f"The key returned {error.code.name}. Reconnect it and try again.")
    if isinstance(error, TimeoutError):
        return str(error)
    if isinstance(error, OSError):
        return "The key could not be accessed. Reconnect it and rescan; if it remains unavailable, check USB permissions."
    return str(error)

@dataclass
class Credential:
    rp: str
    name: str
    display_name: str
    user_id: bytes
    credential_id: bytes

    @property
    def descriptor(self):
        return PublicKeyCredentialDescriptor(type="public-key", id=self.credential_id)

class Hardware:
    def __init__(self):
        self.devices = []
        self.device = self.ctap = self.manager = None
        self.can_edit = False

    def lock(self):
        self.manager = None
        self.ctap = None
        self.device = None
        self.can_edit = False

    def close(self):
        self.lock()
        for device in self.devices:
            device.close()
        self.devices = []

    def scan(self):
        self.close()
        self.devices = list(CtapHidDevice.list_devices())
        names = [d.descriptor.product_name or "FIDO security key" for d in self.devices]
        return [name + (f" · {device.descriptor.serial_number}" if device.descriptor.serial_number else
                        f" · USB key {index + 1}" if names.count(name) > 1 else "")
                for index, (name, device) in enumerate(zip(names, self.devices))]

    def inspect_key(self, index):
        device = self.devices[index]
        try:
            ctap = Ctap2(device)
        except (ValueError, CtapError) as error:
            if isinstance(error, CtapError) and error.code != CtapError.ERR.INVALID_COMMAND:
                raise
            return KeyInfo(fido2=False, pin_set=None, credential_management=False,
                           serial=device.descriptor.serial_number)
        info = ctap.info
        result = KeyInfo(pin_set=info.options.get('clientPin'),
                         credential_management=CM.is_supported(info),
                         min_pin_length=info.min_pin_length,
                         max_pin_length=min(info.max_pin_length, 63),
                         force_pin_change=info.force_pin_change,
                         serial=device.descriptor.serial_number)
        if result.pin_set:
            try:
                result.retries, result.temporarily_blocked = ClientPin(ctap).get_pin_retries()
            except CtapError as error:
                if error.code == CtapError.ERR.PIN_BLOCKED:
                    result.retries = 0
                elif error.code == CtapError.ERR.PIN_AUTH_BLOCKED:
                    result.temporarily_blocked = True
                elif error.code != CtapError.ERR.INVALID_COMMAND:
                    raise
        return result

    def set_pin(self, index, new_pin, old_pin=None):
        self.lock()
        ctap = Ctap2(self.devices[index])
        error = validate_pin(new_pin, ctap.info.min_pin_length, min(ctap.info.max_pin_length, 63))
        if error:
            raise ValueError(error)
        client = ClientPin(ctap)
        if old_pin is None:
            client.set_pin(new_pin)
        else:
            client.change_pin(old_pin, new_pin)

    def reset(self, index, cancel, progress, reconnect_timeout=60, touch_timeout=30):
        """Require all keys removed, then one matching key reinserted, before RESET.

        Never retry RESET automatically. A model without a serial cannot be uniquely
        identified: the UI requires reconnecting only the intended physical key.
        """
        target = self.devices[index].descriptor
        target_aaguid = Ctap2(self.devices[index]).info.aaguid
        def matches(candidate):
            return ((candidate.vid, candidate.pid) == (target.vid, target.pid)
                    and (not target.serial_number or candidate.serial_number == target.serial_number))
        self.close()
        deadline = time.monotonic() + reconnect_timeout
        removed = False
        progress("Unplug all security keys. Keep only the key you want to reset nearby.")
        while True:
            if cancel.is_set():
                raise OperationCancelled("Reset cancelled before sending the reset request.")
            if time.monotonic() >= deadline:
                raise TimeoutError("Reconnect timed out. Start reset again and follow the unplug/reconnect steps.")
            descriptors = list(list_descriptors())
            if not removed:
                if not descriptors:
                    removed = True
                    progress("Reconnect only the key you chose to reset, then be ready to touch it.")
            elif descriptors:
                if len(descriptors) != 1:
                    raise ValueError("More than one key was connected. Reset stopped; start again with only the intended key.")
                candidate = descriptors[0]
                if not matches(candidate):
                    raise ValueError("A different key was connected. Reset stopped; reconnect the selected key and start again.")
                device = open_device(candidate.path)
                try:
                    if not matches(device.descriptor):
                        raise ValueError("The connected key changed while opening it. Reset stopped.")
                    ctap = Ctap2(device)
                    if ctap.info.aaguid != target_aaguid:
                        raise ValueError("The reconnected key does not match. Reset stopped.")
                    if cancel.is_set():
                        raise OperationCancelled("Reset cancelled before sending the reset request.")
                    progress("Touch your key to confirm the reset. If it requires a long touch, hold until it responds.")
                    timer = Timer(touch_timeout, cancel.set)
                    timer.start()
                    try:
                        ctap.reset(event=cancel)
                    except CtapError as error:
                        if error.code == CtapError.ERR.KEEPALIVE_CANCEL:
                            raise OperationCancelled("Reset was not confirmed (cancelled or timed out). Reconnect and check the key before retrying.") from error
                        raise
                    finally:
                        timer.cancel()
                    return
                finally:
                    device.close()
            cancel.wait(0.2)

    def unlock(self, index, pin):
        self.lock()
        device = self.devices[index]
        ctap = Ctap2(device)
        if not CM.is_supported(ctap.info):
            raise ValueError("This key does not support resident credential management.")
        if not ctap.info.options.get("clientPin"):
            raise ValueError("Set a FIDO2 PIN with your key manufacturer's tool first.")
        client = ClientPin(ctap)
        token = client.get_pin_token(pin, permissions=ClientPin.PERMISSION.CREDENTIAL_MGMT)
        self.device, self.ctap = device, ctap
        self.manager = CM(ctap, client.protocol, token)
        self.can_edit = CM.is_update_supported(ctap.info)
        return self.read()

    def read(self):
        if self.manager is None:
            raise ValueError("Unlock your key first.")
        meta = self.manager.get_metadata()
        count = meta[CM.RESULT.EXISTING_CRED_COUNT]
        credentials = []
        if count:
            for rp in self.manager.enumerate_rps():
                for entry in self.manager.enumerate_creds(rp[CM.RESULT.RP_ID_HASH]):
                    user = entry[CM.RESULT.USER]
                    credentials.append(Credential(
                        rp[CM.RESULT.RP]["id"], user.get("name", ""),
                        user.get("displayName", ""), user["id"],
                        entry[CM.RESULT.CREDENTIAL_ID]["id"]))
        return credentials, meta[CM.RESULT.MAX_REMAINING_COUNT]

    def update(self, credential, name, display_name):
        if self.manager is None:
            raise ValueError("Unlock your key first.")
        if not self.can_edit:
            raise ValueError("This key does not support editing user information.")
        self.manager.update_user_info(credential.descriptor,
            PublicKeyCredentialUserEntity(id=credential.user_id, name=name, display_name=display_name))
        return self.read()

    def delete(self, credential):
        if self.manager is None:
            raise ValueError("Unlock your key first.")
        self.manager.delete_cred(credential.descriptor)
        return self.read()

    def create_local(self, pin, name, display_name):
        if self.ctap is None:
            raise ValueError("Unlock your key first.")
        client = ClientPin(self.ctap)
        token = client.get_pin_token(pin, permissions=ClientPin.PERMISSION.MAKE_CREDENTIAL,
                                     permissions_rpid=LOCAL_RP)
        challenge_hash = hashlib.sha256(os.urandom(32)).digest()
        stop = Event()
        timer = Timer(45, stop.set)
        timer.start()
        try:
            self.ctap.make_credential(challenge_hash,
                {"id": LOCAL_RP, "name": "FIDO Manager · local test"},
                {"id": os.urandom(32), "name": name, "displayName": display_name},
                [{"type": "public-key", "alg": -7}], options={"rk": True},
                pin_uv_param=client.protocol.authenticate(token, challenge_hash),
                pin_uv_protocol=client.protocol.VERSION, event=stop)
        finally:
            timer.cancel()
        # A fresh management token is needed after changing token permissions.
        index = self.devices.index(self.device)
        return self.unlock(index, pin)

class Demo:
    """An isolated, in-memory preview. Never accesses hardware."""
    can_edit = True
    def __init__(self):
        self.info = KeyInfo(serial='DEMO-001', retries=8)
        self.rows = [Credential(rp, name, display, os.urandom(16), os.urandom(32))
                     for rp, name, display in [
                         ("github.com", "alex@studio.dev", "Alex Morgan"),
                         ("accounts.google.com", "alex@studio.dev", "Personal account"),
                         ("login.microsoft.com", "alex@work.dev", "Work account")]]
    def scan(self): return ["Studio key · demo"]
    def inspect_key(self, index): return self.info
    def set_pin(self, index, new_pin, old_pin=None):
        error = validate_pin(new_pin, self.info.min_pin_length, self.info.max_pin_length)
        if error: raise ValueError(error)
        self.info.pin_set = True
        self.info.force_pin_change = False
        self.info.retries = 8
    def reset(self, index, cancel, progress, **_):
        progress("Demo: simulating reconnect and touch. No hardware is accessed.")
        if cancel.wait(0.5): raise OperationCancelled("Demo reset cancelled.")
        self.rows.clear()
        self.info.pin_set = False
        self.info.retries = None
    def unlock(self, index, pin): return self.read()
    def read(self): return list(self.rows), 50-len(self.rows)
    def update(self, credential, name, display_name):
        credential.name, credential.display_name = name, display_name
        return self.read()
    def delete(self, credential):
        self.rows.remove(credential)
        return self.read()
    def create_local(self, pin, name, display_name):
        self.rows.append(Credential(LOCAL_RP, name, display_name, os.urandom(32), os.urandom(32)))
        return self.read()
    def lock(self): pass
    def close(self): pass

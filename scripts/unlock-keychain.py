#!/usr/bin/env python3
"""unlock a keychain with the password read from a file, never from argv

usage: unlock-keychain.py KEYCHAIN PASS_FILE
`security unlock-keychain -p` leaks the password into ps; this calls SecKeychainUnlock instead
"""
import ctypes
import sys
from pathlib import Path


def unlock(keychain: str, pass_file: str) -> int:
    sec = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
    sec.SecKeychainOpen.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
    sec.SecKeychainOpen.restype = ctypes.c_int32
    sec.SecKeychainUnlock.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_bool]
    sec.SecKeychainUnlock.restype = ctypes.c_int32
    ref = ctypes.c_void_p()
    status = sec.SecKeychainOpen(keychain.encode(), ctypes.byref(ref))
    if status != 0:
        return status
    try:
        password = Path(pass_file).read_bytes().rstrip(b"\r\n")
    except OSError as err:
        sys.exit(f"cannot read password file: {err}")
    return sec.SecKeychainUnlock(ref, len(password), password, True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    status = unlock(sys.argv[1], sys.argv[2])
    if status != 0:
        reason = {-25293: "wrong password", -25294: "keychain not found"}.get(status, f"OSStatus {status}")
        sys.exit(f"unlock failed: {reason}")

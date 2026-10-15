"""CoreMediaIO device controls through ctypes; no PyObjC needed."""

import ctypes
import struct

_FRAMEWORKS = "/System/Library/Frameworks"
_SYSTEM_OBJECT = 1
_ELEMENT_MAIN = 0
_UTF8 = 0x08000100


def fourcc(code: str) -> int:
    return int.from_bytes(code.encode("ascii"), "big")


_GLOBAL = fourcc("glob")


class _Address(ctypes.Structure):
    _fields_ = [
        ("selector", ctypes.c_uint32),
        ("scope", ctypes.c_uint32),
        ("element", ctypes.c_uint32),
    ]


class CoreMediaIO:
    """Reads and writes properties of the controls a camera's driver publishes."""

    def __init__(self) -> None:
        self._cmio = ctypes.CDLL(f"{_FRAMEWORKS}/CoreMediaIO.framework/CoreMediaIO")
        self._cf = ctypes.CDLL(f"{_FRAMEWORKS}/CoreFoundation.framework/CoreFoundation")
        address = ctypes.POINTER(_Address)
        size = ctypes.POINTER(ctypes.c_uint32)
        self._cmio.CMIOObjectGetPropertyDataSize.argtypes = [
            ctypes.c_uint32,
            address,
            ctypes.c_uint32,
            ctypes.c_void_p,
            size,
        ]
        self._cmio.CMIOObjectGetPropertyData.argtypes = [
            ctypes.c_uint32,
            address,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            size,
            ctypes.c_void_p,
        ]
        self._cmio.CMIOObjectSetPropertyData.argtypes = [
            ctypes.c_uint32,
            address,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        for name in (
            "CMIOObjectGetPropertyDataSize",
            "CMIOObjectGetPropertyData",
            "CMIOObjectSetPropertyData",
        ):
            getattr(self._cmio, name).restype = ctypes.c_int32
        self._cf.CFStringGetCString.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_long,
            ctypes.c_uint32,
        ]
        self._cf.CFStringGetCString.restype = ctypes.c_bool
        self._cf.CFRelease.argtypes = [ctypes.c_void_p]

    def read(self, target: int, selector: str) -> bytes | None:
        address = _Address(fourcc(selector), _GLOBAL, _ELEMENT_MAIN)
        size = ctypes.c_uint32()
        if self._cmio.CMIOObjectGetPropertyDataSize(
            target, ctypes.byref(address), 0, None, ctypes.byref(size)
        ):
            return None
        data = ctypes.create_string_buffer(size.value)
        used = ctypes.c_uint32()
        if self._cmio.CMIOObjectGetPropertyData(
            target, ctypes.byref(address), 0, None, size, ctypes.byref(used), data
        ):
            return None
        return data.raw[: used.value]

    def write(self, target: int, selector: str, data: bytes) -> bool:
        address = _Address(fourcc(selector), _GLOBAL, _ELEMENT_MAIN)
        return not self._cmio.CMIOObjectSetPropertyData(
            target, ctypes.byref(address), 0, None, len(data), data
        )

    def _objects(self, target: int, selector: str) -> list[int]:
        data = self.read(target, selector) or b""
        return list(struct.unpack(f"={len(data) // 4}I", data[: len(data) // 4 * 4]))

    def _uid(self, device: int) -> str | None:
        data = self.read(device, "uid ")
        if data is None or len(data) != ctypes.sizeof(ctypes.c_void_p):
            return None
        string = ctypes.c_void_p.from_buffer_copy(data).value
        if not string:
            return None
        text = ctypes.create_string_buffer(1024)
        try:
            if not self._cf.CFStringGetCString(string, text, len(text), _UTF8):
                return None
        finally:
            self._cf.CFRelease(string)
        return text.value.decode()

    def controls(self, device_uid: str) -> dict[str, int]:
        """Control class codes, such as xpsr for exposure, to their objects."""
        for device in self._objects(_SYSTEM_OBJECT, "dev#"):
            if self._uid(device) != device_uid:
                continue
            found = {}
            for control in self._objects(device, "ownd"):
                kind = self.read(control, "clas")
                if kind is not None and len(kind) == 4:
                    code = struct.unpack("=I", kind)[0].to_bytes(4, "big")
                    found[code.decode("latin-1")] = control
            return found
        return {}

# -*- coding: utf-8 -*-
"""敏感配置文件的 DPAPI 透明加密（需求 #6 / v1.2.1）。

覆盖文件：config.json（含 B站 Cookie）、credential.json（含 QQ音乐 musickey）、
quota_state.json。加密 = Windows DPAPI（crypt32.CryptProtectData），
密钥绑定 当前机器+当前用户，不落盘任何密钥文件，零第三方依赖。

存储格式（同一文件路径，不新增文件）：
    {"__enc__": 1, "data": "<base64 of DPAPI blob>"}

兼容与迁移：
  - read_json 读到老明文文件 → 原样返回（调用方无感知）；
  - write_json 一律写加密格式（DPAPI 不可用时自动回退明文，功能不拦路）；
  - migrate_plaintext 在程序启动时把已存在的明文文件重写为加密文件。

DPAPI 局限（用户知情）：同机同用户的任何进程也能解——它防的是
"文件被拷走/别人拿到备份"，不防本机恶意软件。相比明文已经是质变。
"""

import base64
import ctypes
import json
import os
import ctypes.wintypes as wintypes
from ctypes import byref, c_void_p

MARK = "__enc__"          # 密文文件标记字段
_PROMPT = b"diangetai"    # 附加熵：别的程序调 DPAPI 解不出，除非知道这个串

_crypt32 = None
_kernel32 = None
if os.name == "nt":
    try:
        _crypt32 = ctypes.WinDLL("crypt32")
        _kernel32 = ctypes.WinDLL("kernel32")   # LocalFree 在这（crypt32 不导出）
        _kernel32.LocalFree.argtypes = [c_void_p]
    except Exception:
        _crypt32 = None


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", c_void_p)]


def _blob_to_bytes(blob):
    buf = ctypes.create_string_buffer(blob.cbData)
    ctypes.memmove(buf, blob.pbData, blob.cbData)
    if _kernel32 is not None:
        _kernel32.LocalFree(blob.pbData)
    return buf.raw


def dpapi_available():
    return _crypt32 is not None


def _protect(data: bytes) -> bytes:
    prompt = _PROMPT
    in_blob = _DATA_BLOB(len(data), ctypes.cast(ctypes.c_char_p(data), c_void_p))
    out_blob = _DATA_BLOB()
    if not _crypt32.CryptProtectData(byref(in_blob), "DianGeTai",
                                     byref(_DATA_BLOB(len(prompt),
                                         ctypes.cast(ctypes.c_char_p(prompt), c_void_p))),
                                     None, None, 0, byref(out_blob)):
        raise OSError("CryptProtectData failed")
    return _blob_to_bytes(out_blob)


def _unprotect(data: bytes) -> bytes:
    prompt = _PROMPT
    in_blob = _DATA_BLOB(len(data), ctypes.cast(ctypes.c_char_p(data), c_void_p))
    out_blob = _DATA_BLOB()
    if not _crypt32.CryptUnprotectData(byref(in_blob), None,
                                       byref(_DATA_BLOB(len(prompt),
                                           ctypes.cast(ctypes.c_char_p(prompt), c_void_p))),
                                       None, None, 0, byref(out_blob)):
        raise OSError("CryptUnprotectData failed")
    return _blob_to_bytes(out_blob)


def is_encrypted_payload(obj):
    return isinstance(obj, dict) and obj.get(MARK) == 1 and isinstance(obj.get("data"), str)


def read_json(path, default=None):
    """读 JSON 文件；密文自动解密，明文原样返回（透明）。失败返回 default。"""
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
    except Exception:
        return default
    if is_encrypted_payload(obj):
        try:
            raw = _unprotect(base64.b64decode(obj["data"]))
            return json.loads(raw.decode("utf-8"))
        except Exception:
            # 解不开 = 换了机器/换了用户/文件损坏。返回 default，
            # 上层按"未登录"处理即可，不能崩。
            return default
    return obj


def write_json(path, obj):
    """写 JSON 文件：DPAPI 可用写密文，不可用回退明文。原子替换防半包。"""
    text = json.dumps(obj, ensure_ascii=False, indent=4)
    payload = None
    if _crypt32 is not None:
        try:
            blob = _protect(text.encode("utf-8"))
            payload = json.dumps({MARK: 1, "data": base64.b64encode(blob).decode()})
        except Exception:
            payload = None
    if payload is None:
        payload = text
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(payload)
    os.replace(tmp, path)


def migrate_plaintext(path):
    """启动时调用：文件存在且是明文 → 重写为密文。返回是否发生了迁移。"""
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
    except Exception:
        return False
    if is_encrypted_payload(obj):
        return False          # 已是密文
    if not dpapi_available():
        return False          # 本机没法加密，保持明文别折腾
    try:
        write_json(path, obj)
        return True
    except Exception:
        return False


def wants_manual_edit_hint(path):
    """给使用说明/日志用：文件是否还是明文（迁移失败的兜底状态）。"""
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            head = f.read(256)
        return MARK not in head
    except Exception:
        return False

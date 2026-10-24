"""Apple ID personal signing window. Secrets are passed only through child pipes."""
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import ctypes
from i18n import tr as _t
VERSION = '0.5.0'
BASE = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
BUNDLE = Path(getattr(sys, '_MEIPASS', BASE))

def protect_bytes(data, decrypt=False):
    """Windows current-user DPAPI; never write plaintext key material."""
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, output = (Blob(len(data), buffer), Blob())
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise OSError('Windows protected storage failed')
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.memset(output.data, 0, output.size)
        kernel.LocalFree(output.data)
        ctypes.memset(buffer, 0, len(data))

def key_storage(data, base=BASE):
    key = data.get('key', '')
    if not re.fullmatch('[0-9a-f]{64}/key', key):
        raise ValueError('Unsupported protected key')
    folder = base / '.签名密钥'
    folder.mkdir(exist_ok=True)
    path = folder / (key[:64] + '.dpapi')
    if data.get('op') == 'retrieve':
        return {'ok': True, 'value': protect_bytes(path.read_bytes(), True).decode('utf-8') if path.exists() else None}
    if data.get('op') == 'store' and isinstance(data.get('value'), str):
        encrypted = protect_bytes(data['value'].encode('utf-8'))
        with path.open('xb') as handle:
            handle.write(encrypted)
        return {'ok': True}
    raise ValueError('Unsupported protected operation')

def validate(email, password, udid, ipa, consent):
    if not email.strip() or not password:
        return _t('请填写 Apple ID 和登录密码。')
    if not re.fullmatch('(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{8}-[0-9a-fA-F]{16})', udid.strip()):
        return _t('UDID 格式无效，请从爱思设备信息中完整复制。')
    if not Path(ipa).is_file() or Path(ipa).suffix.lower() != '.ipa':
        return _t('请选择一个存在的 IPA 文件。')
    if not consent:
        return _t('请先阅读并勾选下方服务与签名说明。')
    return None

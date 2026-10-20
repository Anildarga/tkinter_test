import ctypes
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

PROCESS_SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
ERROR_INVALID_PARAMETER = 87


def wait_for_process(pid):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int

    handle = kernel32.OpenProcess(PROCESS_SYNCHRONIZE, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == ERROR_INVALID_PARAMETER:
            return
        raise ctypes.WinError(error)

    try:
        result = kernel32.WaitForSingleObject(handle, 120_000)
        if result == WAIT_TIMEOUT:
            raise TimeoutError("The application did not close within 120 seconds.")
        if result != WAIT_OBJECT_0:
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(handle)


def replace_when_unlocked(source, destination):
    deadline = time.monotonic() + 10
    while True:
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.2)


def install_update(target, downloaded, pid):
    target = Path(target).resolve()
    downloaded = Path(downloaded).resolve()

    if not target.is_file():
        raise FileNotFoundError(f"Installed executable not found: {target}")
    if not downloaded.is_file():
        raise FileNotFoundError(f"Update executable not found: {downloaded}")
    if target.suffix.lower() != ".exe" or downloaded.suffix.lower() != ".exe":
        raise ValueError("Both files must be Windows .exe files.")
    if target == downloaded:
        raise ValueError("The update file must be separate from the installed app.")
    if pid <= 0:
        raise ValueError("Process ID must be a positive integer.")

    wait_for_process(pid)

    token = uuid.uuid4().hex
    staged = target.with_name(f"{target.stem}.new-{token}.exe")
    backup = target.with_name(f"{target.stem}.backup-{token}.exe")
    shutil.copy2(downloaded, staged)

    try:
        replace_when_unlocked(target, backup)
        replace_when_unlocked(staged, target)
        subprocess.Popen([str(target)], cwd=str(target.parent))
    except Exception:
        if target.exists() and backup.exists():
            target.unlink()
        if backup.exists() and not target.exists():
            os.replace(backup, target)
        raise

    print(f"Update installed. Previous version backed up to: {backup}")
    try:
        downloaded.unlink()
        downloaded.parent.rmdir()
    except OSError as error:
        print(f"Warning: could not remove downloaded update files: {error}")


def main():
    if len(sys.argv) != 4:
        print(
            "Usage: Updater.exe <installed.exe> <new.exe> <process_id>",
            file=sys.stderr,
        )
        raise SystemExit(2)

    target, downloaded, pid_text = sys.argv[1:]
    try:
        pid = int(pid_text)
    except ValueError:
        raise ValueError("Process ID must be an integer.") from None
    install_update(target, downloaded, pid)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TimeoutError) as error:
        print(f"Updater failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None

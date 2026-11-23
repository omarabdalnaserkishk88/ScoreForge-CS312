"""Local backend for the native Windows Forms client; no browser is opened."""
import os
import argparse
import threading
import time
from pathlib import Path
from server import Server,Store
parser=argparse.ArgumentParser()
parser.add_argument('--parent-pid',type=int)
args=parser.parse_args()
base=Path(os.getenv('SCOREFORGE_DATA_DIR') or Path(os.getenv('LOCALAPPDATA',str(Path.home())))/'ScoreForge')
store=Store(base/'scoreforge.db')
server=None
for port in (5050,8081,8765,0):
    try:
        server=Server(('127.0.0.1',port),store);break
    except OSError:continue
if server is None:raise SystemExit('Unable to open a loopback port.')
print(f'READY http://127.0.0.1:{server.server_port}',flush=True)
print(f'Database: {base / "scoreforge.db"}',flush=True)
def watch_parent():
    if os.name!='nt' or not args.parent_pid:return
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x00100000,False,args.parent_pid)
    if not handle:return
    try:kernel.WaitForSingleObject(handle,0xFFFFFFFF)
    finally:kernel.CloseHandle(handle)
    # Let the current 30-second rounds finish before stopping our own server.
    cutoff=time.monotonic()+35
    while time.monotonic()<cutoff:
        if not store.query("SELECT 1 FROM rounds WHERE status='active' LIMIT 1"):break
        time.sleep(.5)
    server.shutdown()
threading.Thread(target=watch_parent,daemon=True).start()
try:server.serve_forever()
except KeyboardInterrupt:pass
finally:server.server_close()

#!/usr/bin/env python3
"""
stdio 过滤 wrapper - 给 sinataoke_cn 套一层过滤器
问题: sinataoke_cn 把 "[timestamp] 加载环境变量..." 这种启动日志
      打到 stdout，污染了 MCP JSON-RPC 通道，导致 pydantic 解析失败。
方案: 这个脚本作为中间人:
      - 启动 sinataoke_cn 作为子进程
      - 只把以 '{' 开头的行(JSON-RPC消息)转发到 stdout
      - 其他所有噪音日志丢弃
      - stderr 也全部丢弃
      - stdin 透传给 sinataoke_cn
      - 退出时强制清理子进程
"""
import sys
import os
import subprocess
import threading
import signal
 
SINATAOKE_VERSION = os.environ.get("SINATAOKE_VERSION", "2.0.5")
 
proc = subprocess.Popen(
    [
        "npx",
        "--prefer-offline",
        "--yes",
        f"@liuliang520500/sinataoke_cn@{SINATAOKE_VERSION}",
        "/tmp/",
    ],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    bufsize=0,
)
 
def cleanup(*_):
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
    except Exception:
        pass
    sys.exit(0)
 
signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)
 
def stdin_forwarder():
    try:
        while True:
            data = sys.stdin.buffer.read1(4096)
            if not data:
                break
            proc.stdin.write(data)
            proc.stdin.flush()
    except Exception:
        pass
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
 
t = threading.Thread(target=stdin_forwarder, daemon=True)
t.start()
 
try:
    for line in proc.stdout:
        stripped = line.lstrip()
        if stripped.startswith(b'{'):
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
except Exception:
    pass
finally:
    cleanup()

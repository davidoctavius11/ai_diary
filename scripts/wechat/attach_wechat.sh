#!/bin/bash
echo "Waiting for WeChat to launch..."
until pgrep WeChat > /dev/null; do sleep 0.2; done
PID=$(pgrep WeChat | head -1)
echo "WeChat found (PID $PID) — attaching LLDB..."
lldb -p "$PID" -s "$(dirname "$0")/wechat_grab_key.lldb"

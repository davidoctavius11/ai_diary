#!/bin/bash
PID=$(pgrep WeChat | head -1)
echo "Attaching Frida to WeChat PID $PID..."
sudo frida -p "$PID" -l "$(dirname "$0")/frida_wechat_key.js"

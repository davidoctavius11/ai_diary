"""
wechat_key_printer.py
---------------------
lldb Python callback — called each time sqlite3_key breakpoint fires.
Reads 32 bytes from $x1 (arm64 second argument = the raw cipher key),
prints the hex string, and saves it to /tmp/wechat_key.txt.

Run via: sudo lldb -p $(pgrep WeChat | head -1) -s scripts/wechat_grab_key.lldb
"""

import lldb


def handle_breakpoint(frame, bp_loc, dict):
    """Called by lldb each time sqlite3_key is hit."""
    # $x1 holds the pointer to the 32-byte key (arm64 calling convention)
    x1 = frame.FindRegister("x1").GetValueAsUnsigned()
    if x1 == 0:
        print("[wechat_key] $x1 is NULL — skipping")
        return False

    process = frame.GetThread().GetProcess()
    error = lldb.SBError()
    raw = process.ReadMemory(x1, 32, error)

    if error.Fail() or not raw:
        print(f"[wechat_key] memory read failed: {error}")
        return False

    hex_key = raw.hex()
    print(f"\n{'='*60}")
    print(f"[wechat_key] sqlite3_key intercepted!")
    print(f"[wechat_key] RAW HEX KEY (64 chars): {hex_key}")
    print(f"{'='*60}\n")

    # Save to file so the decrypt script can read it
    with open("/tmp/wechat_key.txt", "w") as f:
        f.write(hex_key + "\n")
    print("[wechat_key] Key saved to /tmp/wechat_key.txt")

    # Continue after first key — comment out to capture all keys
    return False  # False = don't stop execution

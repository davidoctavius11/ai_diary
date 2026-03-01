"""
decrypt_wechat_db.py
---------------------
Decrypts WeChat Mac 4.x SQLCipher databases using the key extracted by
the lldb script (wechat_grab_key.lldb + wechat_key_printer.py).

Reads key from /tmp/wechat_key.txt (64-char hex string).
Decrypts all message_*.db files to data/wechat/decrypted/.

Requires: brew install sqlcipher  (already done)

Usage:
    python scripts/decrypt_wechat_db.py
    python scripts/decrypt_wechat_db.py --key <64-char-hex>   # override key
"""

import argparse
import glob
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR    = Path(__file__).parent.parent
WECHAT_DIR  = Path.home() / "Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files"
OUT_DIR     = BASE_DIR / "data" / "wechat" / "decrypted"
KEY_FILE    = Path("/tmp/wechat_key.txt")
SQLCIPHER   = shutil.which("sqlcipher") or "/opt/homebrew/bin/sqlcipher"

# WeChat 4.x / SQLCipher 4 / WCDB 2.x parameters
CIPHER_PRAGMAS = """
PRAGMA cipher_page_size = 4096;
PRAGMA kdf_iter = 256000;
PRAGMA kdf_algorithm = PBKDF2_HMAC_SHA512;
PRAGMA hmac_algorithm = HMAC_SHA512;
"""


def get_key(override: str | None) -> str:
    if override:
        return override.strip().lower()
    if KEY_FILE.exists():
        key = KEY_FILE.read_text().strip().lower()
        if len(key) == 64:
            return key
        print(f"✗ /tmp/wechat_key.txt exists but looks wrong (len={len(key)})")
    print("✗ Key not found. Run the lldb capture script first:")
    print("    sudo lldb -p $(pgrep WeChat | head -1) -s scripts/wechat_grab_key.lldb")
    sys.exit(1)


def find_message_dbs() -> list[Path]:
    """Find all message_*.db files under the WeChat xwechat_files directory."""
    pattern = str(WECHAT_DIR / "**" / "db_storage" / "message" / "message_*.db")
    dbs = [Path(p) for p in glob.glob(pattern, recursive=True)
           if not p.endswith("-shm") and not p.endswith("-wal")]
    return sorted(dbs)


def decrypt_db(db_path: Path, key_hex: str, out_path: Path) -> bool:
    """Decrypt a single SQLCipher db to a plain SQLite file via sqlcipher CLI."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    script = f"""
PRAGMA key = "x'{key_hex}'";
{CIPHER_PRAGMAS}
ATTACH DATABASE '{out_path}' AS plaintext KEY '';
SELECT sqlcipher_export('plaintext');
DETACH DATABASE plaintext;
"""
    result = subprocess.run(
        [SQLCIPHER, str(db_path)],
        input=script,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0 or "Error" in result.stderr:
        print(f"  ✗ {db_path.name}: {result.stderr.strip()[:200]}")
        return False

    # Verify the output is a valid SQLite file
    verify = subprocess.run(
        [SQLCIPHER, str(out_path), ".tables"],
        capture_output=True, text=True
    )
    if verify.returncode != 0:
        print(f"  ✗ {db_path.name}: output not readable — key may be wrong")
        out_path.unlink(missing_ok=True)
        return False

    tables = verify.stdout.strip()
    print(f"  ✓ {db_path.name} → {out_path.name}  [{tables[:80]}]")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", help="64-char hex key (overrides /tmp/wechat_key.txt)")
    args = parser.parse_args()

    key = get_key(args.key)
    print(f"Using key: {key[:8]}...{key[-8:]}")

    dbs = find_message_dbs()
    if not dbs:
        print(f"✗ No message_*.db files found under {WECHAT_DIR}")
        sys.exit(1)

    print(f"\nFound {len(dbs)} database(s):")
    for db in dbs:
        print(f"  {db.name}  ({db.stat().st_size // 1024} KB)")

    print(f"\nDecrypting to {OUT_DIR}/")
    ok = 0
    for db in dbs:
        out = OUT_DIR / db.name.replace(".db", "_plain.db")
        if decrypt_db(db, key, out):
            ok += 1

    print(f"\n{'✓' if ok == len(dbs) else '!'} {ok}/{len(dbs)} databases decrypted")
    if ok > 0:
        print(f"\nNext step: python scripts/parse_wechat.py")


if __name__ == "__main__":
    main()

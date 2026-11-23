#!/usr/bin/env python3
"""Export the two service environment files with systemd's native quoting rules."""
import os
import re
import subprocess
import sys
from pathlib import Path

CONFIG = Path("/etc/gilead-ai4bi")


def export(role):
    source = CONFIG / f"{role}.env"
    target = CONFIG / "compose" / f"{role}.env"
    names = []
    for line in source.read_text().splitlines():
        match = re.match(r"^\s*([A-Za-z_][A-Za-z_0-9]*)\s*=", line)
        if match and match[1] not in names:
            names.append(match[1])
    if not names:
        raise ValueError(f"No environment entries in {source}")
    entries = []
    for name in names:
        value = os.environ[name]
        if "\n" in value or "\r" in value:
            raise ValueError(f"{name} contains a newline and requires a mounted secret")
        entries.append(f"{name}={value}\n")
    target.parent.mkdir(mode=0o700, exist_ok=True)
    tmp = target.with_suffix(f".tmp-{os.getpid()}")
    try:
        with tmp.open("x") as stream:
            stream.writelines(entries)
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    os.umask(0o077)
    if len(sys.argv) == 3 and sys.argv[1] == "--export" and sys.argv[2] in ("application", "platform"):
        export(sys.argv[2])
    else:
        for role in ("application", "platform"):
            subprocess.run([
                "systemd-run", "--quiet", "--wait", "--pipe", "--collect",
                f"--property=EnvironmentFile={CONFIG}/{role}.env",
                sys.executable, str(Path(__file__).resolve()), "--export", role,
            ], check=True)

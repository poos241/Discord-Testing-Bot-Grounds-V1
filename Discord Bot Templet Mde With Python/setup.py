#!/usr/bin/env python3
"""
One-shot setup for the Discord bot.

Run from the project folder (the one containing bot.py):

    python setup.py

What it does:
  1. Checks Python is 3.10+
  2. Installs everything in requirements.txt
  3. Verifies each dependency actually imports
  4. Creates .env (from .env.example) if missing
  5. Byte-compiles cogs/ to catch syntax errors

It stays up to date automatically: the package list comes straight from
requirements.txt and the cog list is scanned from cogs/ — so when the bot
gains a new dependency or cog, setup.py handles it with no code changes.

Safe to run again any time (idempotent).
"""

import compileall
import importlib
import os
import re
import shutil
import subprocess
import sys

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# requirement name -> import name, for the cases a simple guess won't work.
# Anything not listed here falls back to name.lower().replace("-", "_").
KNOWN_IMPORTS = {
    "py-cord": "discord",
    "python-dotenv": "dotenv",
    "pillow": "PIL",
}

ENV_TEMPLATE = "TOKEN2=paste-your-bot-token-here\n"


def step(ok, message):
    print(f"{'✅' if ok else '❌'} {message}")
    return ok


def check_python():
    ok = sys.version_info >= (3, 10)
    return step(ok, f"Python {sys.version.split()[0]}"
                   + (" (3.10+ required)" if not ok else ""))


def parse_requirements(path):
    """Read package names from requirements.txt, ignoring versions/comments."""
    packages = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name = re.split(r"[<>=!~\s\[]", line, maxsplit=1)[0].strip()
            if name:
                packages.append(name)
    return packages


def import_name(package):
    if package in KNOWN_IMPORTS:
        return KNOWN_IMPORTS[package]
    return package.lower().replace("-", "_")


def install_requirements():
    req = os.path.join(PROJECT_DIR, "requirements.txt")
    if not os.path.exists(req):
        return step(False, "requirements.txt not found")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-r", req],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-2000:])
        return step(False, "pip install failed (see above)")
    return step(True, "dependencies installed from requirements.txt")


def verify_imports():
    req = os.path.join(PROJECT_DIR, "requirements.txt")
    packages = parse_requirements(req)
    failed = []
    for pkg in packages:
        mod = import_name(pkg)
        try:
            importlib.import_module(mod)
        except ImportError:
            failed.append(f"{pkg} (import {mod})")
    if failed:
        return step(False, "could not import: " + ", ".join(failed))
    return step(True, f"all {len(packages)} dependencies import cleanly")


def ensure_env():
    env = os.path.join(PROJECT_DIR, ".env")
    if os.path.exists(env):
        return step(True, ".env already exists")
    example = os.path.join(PROJECT_DIR, ".env.example")
    if os.path.exists(example):
        shutil.copy(example, env)
    else:
        with open(env, "w", encoding="utf-8") as f:
            f.write(ENV_TEMPLATE)
    print("   → created .env — open it and put your bot token after TOKEN2=")
    return step(True, ".env created")


def compile_cogs():
    cogs_dir = os.path.join(PROJECT_DIR, "cogs")
    if not os.path.isdir(cogs_dir):
        return step(False, "cogs/ directory not found")
    files = sorted(f for f in os.listdir(cogs_dir) if f.endswith(".py"))
    if not files:
        return step(False, "no .py files in cogs/")
    bad = []
    for f in files:
        path = os.path.join(cogs_dir, f)
        if not compileall.compile_file(path, quiet=1, force=True):
            bad.append(f)
    if bad:
        return step(False, "syntax errors in: " + ", ".join(bad))
    return step(True, f"{len(files)} cogs compile cleanly")


def check_config():
    try:
        import config  # noqa: F401
    except Exception as e:  # noqa: BLE001
        return step(False, f"config.py failed to import: {e}")
    return step(True, "config.py imports cleanly")


def main():
    print("Setting up the Discord bot...\n")
    results = [
        check_python(),
        install_requirements(),
        verify_imports(),
        ensure_env(),
        compile_cogs(),
        check_config(),
    ]
    print()
    if all(results):
        print("All set! Next steps:")
        print("  1. Put your bot token in .env (after TOKEN2=)")
        print("  2. Check OWNER_IDS / GUILD_IDS in config.py")
        print("  3. Run:  python bot.py")
        return 0
    print("Setup hit a problem above — fix it and run python setup.py again.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

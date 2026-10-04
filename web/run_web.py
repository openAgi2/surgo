"""Launcher for the surgo web UI: ``surgo-web`` console entry point.

Derived from TradingAgents-CN's Apache-2.0-licensed ``web/run_web.py``
(cache-cleaning workarounds and psutil process-tree shutdown replaced with
a plain streamlit subprocess).
Copyright 2024-2026 hsliuping & TradingAgents-CN Contributors
Modifications for surgo: Copyright 2026 surgo contributors
SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

APP = Path(__file__).with_name("app.py")


def main(port: int = 8501):
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(APP),
        "--server.port", str(port),
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]
    print(f"surgo web UI → http://localhost:{port}")
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()

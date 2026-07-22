"""Regression test: the production Dockerfile installed the `playwright`
Python package (apps/core/requirements.txt) but never ran
`playwright install chromium` to download the actual browser binary.
`pip install playwright` only installs the driver — without a separate
install step, every Playwright launch() in production (human_browser.py's
stealth browsing, browser_sandbox.py) fails at runtime with "Executable
doesn't exist", because Chromium was never downloaded into the image. The
apt-get block only installs Chromium's OS-level shared library
dependencies, not the browser itself.
"""

from __future__ import annotations

from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[2] / "Dockerfile"


def test_dockerfile_installs_playwright_browser_binary():
    text = DOCKERFILE.read_text()

    pip_install_idx = text.index("pip install --no-cache-dir -r requirements.txt")
    playwright_install_idx = text.index("playwright install chromium")

    assert playwright_install_idx > pip_install_idx, (
        "playwright install chromium must run after pip install (playwright needs "
        "to be importable) and land in the image before it's deployed"
    )


def test_dockerfile_sets_browsers_path_before_install_so_nonroot_user_can_read_it():
    text = DOCKERFILE.read_text()

    browsers_path_idx = text.index("PLAYWRIGHT_BROWSERS_PATH")
    playwright_install_idx = text.index("playwright install chromium")
    useradd_idx = text.index("useradd")

    # The env var must be set before the browser download (so the download
    # lands in that path) and the path must be made world-readable before
    # switching to the non-root `aria` user, since the default
    # /root/.cache/ms-playwright wouldn't be readable by that user.
    assert browsers_path_idx < playwright_install_idx < useradd_idx

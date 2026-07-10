"""
ARIA AI — Legacy Entry Point.
Delegates to the new apps.core.main module.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from apps.core.main import app  # noqa: E402, F401

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    print(f"\n{'='*60}")
    print("🚀 ARIA AI - Autonomous Intelligence Platform")
    print(f"{'='*60}")
    uvicorn.run("apps.core.main:app", host="0.0.0.0", port=port, reload=False)
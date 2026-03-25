"""
Claude Imprint — Agent Entry Point
Starts the heartbeat agent for proactive behaviors.

Usage:
  python3 agent.py
  HEARTBEAT_INTERVAL=300 python3 agent.py   # 5-min heartbeat (testing)
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from heartbeat import main

if __name__ == "__main__":
    print("Starting Claude Imprint Agent...")
    print("=" * 40)
    main()

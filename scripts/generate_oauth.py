#!/usr/bin/env python3
"""
Generate OAuth credentials for Claude Imprint.
Saves client_id, client_secret, and access_token to ~/.imprint-oauth.json.

Usage:
  python3 scripts/generate_oauth.py
"""

import json
from pathlib import Path
from secrets import token_urlsafe

OUTPUT_FILE = Path.home() / ".imprint-oauth.json"


def main():
    credentials = {
        "client_id": token_urlsafe(16),
        "client_secret": token_urlsafe(32),
        "access_token": token_urlsafe(32),
    }

    OUTPUT_FILE.write_text(json.dumps(credentials, indent=2) + "\n", encoding="utf-8")

    print(f"OAuth credentials saved to {OUTPUT_FILE}")
    print()
    for key, value in credentials.items():
        print(f"  {key}: {value}")
    print()
    print("Keep these credentials secure. Do not commit them to version control.")


if __name__ == "__main__":
    main()

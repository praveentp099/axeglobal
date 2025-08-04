import json
import sys

try:
    with open("products_final.json", encoding="utf-8-sig") as f:
        json.load(f)
    print("✓ VALID JSON")
except Exception as e:
    print(f"❌ INVALID JSON: {e}")
    sys.exit(1)

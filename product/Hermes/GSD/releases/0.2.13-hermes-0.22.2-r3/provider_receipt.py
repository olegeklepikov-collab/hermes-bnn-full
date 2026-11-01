#!/usr/bin/env python3
"""Deliver an actual native G completion to the original CommandProvider once bound."""
from pathlib import Path
import argparse
import hashlib
import hmac
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bn_gsd.codec import canonical, digest, read_json

p = argparse.ArgumentParser()
p.add_argument("--receipt", required=True)
p.add_argument("--key", required=True)
a = p.parse_args()
request = read_json(sys.stdin.buffer.read(24 * 1024 * 1024))
receipt = read_json(Path(a.receipt).read_bytes())
key = Path(a.key).read_bytes()
body = receipt["body"]
if not hmac.compare_digest(receipt["mac"], hmac.new(key, canonical(body), hashlib.sha256).hexdigest()):
    raise SystemExit("Invalid native execution receipt")
if time.time() > body["deadline"] or request.get("contract") != "gsd.generation-provider/1":
    raise SystemExit("Expired or incompatible provider delivery")
if digest(request["request"]) != body["request_digest"] or request["context"]["manifest_digest"] != body["context_digest"]:
    raise SystemExit("Native execution was for different inputs or context")
if body["native_receipt"]["terminal_state"] != "SUCCEEDED" or not body["native_receipt"].get("result_hash"):
    raise SystemExit("No actual native completion")
print(canonical({"candidates": body["candidates"]}).decode())

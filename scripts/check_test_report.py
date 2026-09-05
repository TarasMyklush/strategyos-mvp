"""Fail a service release gate on failures, errors, empty reports or skipped proofs."""
import sys
from xml.etree import ElementTree

root = ElementTree.parse(sys.argv[1]).getroot()
cases = root.findall(".//testcase")
bad = [case for case in cases if any(case.find(tag) is not None for tag in ("failure", "error", "skipped"))]
if not cases or bad:
    raise SystemExit(f"Service gate failed: {len(cases)} tests, {len(bad)} failed/errored/skipped.")
print(f"Service gate passed: {len(cases)} tests, zero skips.")

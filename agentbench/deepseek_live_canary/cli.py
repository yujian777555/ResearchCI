"""Checked-in DS-1 entrypoint; R1 live modes fail closed."""
from __future__ import annotations
import argparse
from .preflight import PreflightResult, serialize_preflight_summary

def main(argv=None)->int:
    parser=argparse.ArgumentParser(); parser.add_argument("mode",choices=("offline-selftest","preflight","canary")); args=parser.parse_args(argv)
    if args.mode=="offline-selftest":
        return 0
    print("DS-1 R1 live mode disabled; requires a later Planner authorization")
    return 2
if __name__=="__main__": raise SystemExit(main())

"""Live behavior suite runner: real Milo turns (goose + Claude, the production prompt and milo_context) in a sandbox.

  uv run python tests/live/run.py                      # every case once
  uv run python tests/live/run.py --case email_reply_is_draft --repeat 3
  uv run python tests/live/run.py --area email,schedule --repeat-fuzzy 2
  uv run python tests/live/run.py --list

Writes reports/live/<time>.md and .json (and latest.md). Exit code 1 if a case failed.
Uses the Claude plan: roughly 20-60k tokens per case turn, about 1-2 minutes each.
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from cases import BY_ID, CASES  # noqa: E402
from grading import grade  # noqa: E402
from harness import ROOT, Bridge  # noqa: E402

REPORTS = ROOT / "reports" / "live"


def pick(args) -> list:
    cases = CASES
    if args.case:
        ids = [i for x in args.case for i in x.split(",")]
        missing = [i for i in ids if i not in BY_ID]
        if missing:
            sys.exit(f"unknown case(s): {missing}. --list shows them.")
        cases = [BY_ID[i] for i in ids]
    if args.area:
        areas = {a for x in args.area for a in x.split(",")}
        cases = [c for c in cases if c.area in areas]
    return cases


def status(checks: list[dict]) -> str:
    if any(c["ok"] is False for c in checks):
        return "FAIL"
    return "PASS"


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", action="append", help="case id(s), comma separated")
    ap.add_argument("--area", action="append", help="area(s), comma separated")
    ap.add_argument("--repeat", type=int, default=1, help="runs of every chosen case")
    ap.add_argument("--repeat-fuzzy", type=int, default=0, help="runs of fuzzy cases (overrides --repeat for them)")
    ap.add_argument("--no-judge", action="store_true", help="skip the LLM judge checks")
    ap.add_argument("--keep", action="store_true", help="keep the sandbox folder for a look afterwards")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    cases = pick(args)
    if args.list:
        for c in CASES:
            print(f"{c.id:34} {c.area:9} {'fuzzy ' if c.fuzzy else '      '}{c.title}")
        return 0
    plan = [(c, i) for c in cases if not c.skip
            for i in range(args.repeat_fuzzy if c.fuzzy and args.repeat_fuzzy else args.repeat)]
    print(f"{len(plan)} runs of {len(cases)} cases. Starting the eval bridge...", flush=True)

    bridge = Bridge(port=args.port, keep=args.keep).start()
    started = time.time()
    results = []
    try:
        for n, (case, rep) in enumerate(plan, 1):
            run = await bridge.run_case(case)
            checks = await grade(case, run, use_judge=not args.no_judge)
            st = status(checks)
            failed = [c for c in checks if c["ok"] is False]
            results.append({"case": case.id, "area": case.area, "title": case.title, "rep": rep + 1, "status": st,
                            "fuzzy": case.fuzzy, "seconds": run.seconds, "source": case.source, "checks": checks,
                            "turns": [{"prompt": t.prompt, "reply": t.text, "raw": t.raw, "suggest": t.suggest,
                                       "notes": t.notes, "error": t.error, "seconds": t.seconds, "spoken": t.spoken,
                                       "tools": [{k: c[k] for k in ("tool", "decision", "reason")} |
                                                 {"input": json.dumps(c["input"])[:400]} for c in t.tools]}
                                      for t in run.turns],
                            "google": [{"tool": g["tool"], "args": json.dumps(g["args"])[:400]} for g in run.google],
                            "files": {p: {"kind": d["kind"]} for p, d in run.files.items()}})
            why = "; ".join(f"{c['check']}: {c['detail']}" for c in failed)[:300]
            print(f"[{n}/{len(plan)}] {st:4} {case.id}{f' #{rep + 1}' if rep else ''} ({run.seconds:.0f}s)"
                  + (f"  -- {why}" if why else ""), flush=True)
    finally:
        bridge.stop()
        if args.keep:
            print("sandbox kept at", bridge.box.get("base"))
    return report(results, time.time() - started, args)


def report(results: list[dict], seconds: float, args) -> int:
    by_case: dict[str, list[dict]] = {}
    for r in results:
        by_case.setdefault(r["case"], []).append(r)
    rows = []
    for cid, rs in by_case.items():
        passes = sum(r["status"] == "PASS" for r in rs)
        verdict = "PASS" if passes == len(rs) else "FAIL" if passes == 0 else "FLAKY"
        reasons = sorted({f"{c['check']}: {c['detail']}" for r in rs for c in r["checks"] if c["ok"] is False})
        rows.append({"case": cid, "area": rs[0]["area"], "verdict": verdict, "passes": f"{passes}/{len(rs)}",
                     "seconds": round(sum(r["seconds"] for r in rs) / len(rs)), "reasons": reasons,
                     "title": rs[0]["title"]})
    width = max([len(r["case"]) for r in rows] + [4])
    lines = [f"{'case':{width}}  {'area':9} {'result':6} {'runs':5} {'avg s':>5}  reasons"]
    for r in rows:
        lines.append(f"{r['case']:{width}}  {r['area']:9} {r['verdict']:6} {r['passes']:5} {r['seconds']:>5}  "
                     + ("; ".join(r["reasons"])[:220] or "-"))
    total = {v: sum(r["verdict"] == v for r in rows) for v in ("PASS", "FAIL", "FLAKY")}
    summary = f"{len(rows)} cases, {len(results)} runs in {seconds / 60:.1f} min: " \
              f"{total['PASS']} pass, {total['FAIL']} fail, {total['FLAKY']} flaky"
    print("\n" + "\n".join(lines) + "\n\n" + summary)

    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    data = {"when": datetime.now().isoformat(timespec="seconds"), "summary": summary, "args": vars(args),
            "cases": rows, "runs": results}
    (REPORTS / f"{stamp}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))
    md = [f"# Milo live behavior suite, {data['when']}", "", summary, "",
          "| case | area | result | runs | avg s | reasons |", "|---|---|---|---|---|---|"]
    for r in rows:
        why = "<br>".join(x.replace("|", "\\|")[:300] for x in r["reasons"]) or "-"
        md.append(f"| {r['case']} | {r['area']} | {r['verdict']} | {r['passes']} | {r['seconds']} | {why} |")
    md += ["", "## Runs", ""]
    for r in results:
        md.append(f"### {r['case']} #{r['rep']}: {r['status']} ({r['seconds']:.0f} s)")
        md.append(f"_{r['title']}. Source: {r['source']}_\n")
        for t in r["turns"]:
            md.append(f"- **Alex:** {t['prompt']}")
            md.append(f"- **Milo:** {(t['reply'] or t['error'] or '').strip()[:1500]}".replace("\n", "\n  "))
            if t["suggest"]:
                md.append(f"  - suggest: {t['suggest']}")
            used = [f"{c['tool']}{' (blocked)' if c['decision'] == 'deny' else ''}" for c in t["tools"]
                    if c["tool"] != "ToolSearch"]
            if used:
                md.append(f"  - tools: {', '.join(used)[:600]}")
        for c in r["checks"]:
            mark = {True: "ok", False: "FAIL", None: "skip"}[c["ok"]]
            md.append(f"  - [{mark}] {c['check']}: {c['detail']}")
        md.append("")
    (REPORTS / f"{stamp}.md").write_text("\n".join(md))
    (REPORTS / "latest.md").write_text("\n".join(md))
    print(f"report: {REPORTS / (stamp + '.md')}")
    return 1 if total["FAIL"] or total["FLAKY"] else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

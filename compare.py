"""Side-by-side table of every judge run saved in out/results-*.json."""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).parent / "out"


def cell(row: dict) -> str:
    j = row["judge"]
    if j["majority_pass"] is None:
        return "no verdict"
    tag = "pass" if j["majority_pass"] else "FAIL"
    flag = ""
    if row["verdict"].startswith("MISSED"):
        flag = " MISSED"
    elif row["verdict"].startswith("FALSE"):
        flag = " FALSE ALARM"
    if j["flips"]:
        flag += " unstable"
    return f"{tag} {j['passes']}/{j['valid_runs']} ({j['mean_score']}){flag}"


def main() -> None:
    files = sorted(OUT.glob("results-*.json"))
    if not files:
        raise SystemExit("No out/results-*.json files. Run run_demo.py first and copy out/results.json to out/results-<judge>.json.")
    results = {f.stem.removeprefix("results-"): json.loads(f.read_text()) for f in files}
    judges = list(results)
    scenarios = [r["scenario"] for r in next(iter(results.values()))["rows"]]
    lines = ["| Scenario | Verifier | " + " | ".join(judges) + " |", "|---|---|" + "---|" * len(judges)]
    for name in scenarios:
        rows = {j: next(r for r in results[j]["rows"] if r["scenario"] == name) for j in judges}
        v = "pass" if rows[judges[0]]["verifier"]["pass"] else "FAIL"
        lines.append(f"| `{name}` | {v} | " + " | ".join(cell(rows[j]) for j in judges) + " |")
    lines.append("| **Agreement** | | " + " | ".join(f"{results[j]['agreement']}/{results[j]['scored']}" for j in judges) + " |")
    lines.append("| **Missed failures** | | " + " | ".join(str(results[j]["missed_failures"]) for j in judges) + " |")
    lines.append("| **False alarms** | | " + " | ".join(str(results[j]["false_alarms"]) for j in judges) + " |")
    lines.append("| **Unstable verdicts** | | " + " | ".join(str(len(results[j]["unstable"])) for j in judges) + " |")
    table = "\n".join(lines)
    (OUT / "comparison.md").write_text(table + "\n")
    print(table)


if __name__ == "__main__":
    main()

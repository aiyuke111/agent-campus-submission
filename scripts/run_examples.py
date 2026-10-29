"""一键生成 examples/ 下的实际运行结果与 Trace。

运行：python scripts/run_examples.py
输出：examples/outputs/*.result.json、*.trace.json、drafts.json
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "examples", "outputs")
STORE = os.path.join(OUT, "drafts.json")

SCENARIOS = [
    # (request 文件, 额外 CLI 参数)
    ("request_M05_normal", []),
    ("request_M01_conflict", []),
    ("request_M02_missing", []),
    ("request_M03_risk", []),
    ("request_M04_no_slot", []),
    ("request_M01_duplicate", ["--tag", "second"]),
    ("request_M05_normal", ["--inject", "save_fail", "--tag", "savefail"]),
    ("request_M01_conflict", ["--max-steps", "2", "--tag", "limit"]),
]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    for name in os.listdir(OUT):
        os.remove(os.path.join(OUT, name))
    for req, extra in SCENARIOS:
        cmd = [
            sys.executable, "-m", "src.cli",
            "--request", os.path.join("examples", "inputs", f"{req}.json"),
            "--store", STORE,
            "--outdir", os.path.join("examples", "outputs"),
        ] + extra
        subprocess.run(cmd, cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("done:", req, " ".join(extra))
    print("examples written to", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())

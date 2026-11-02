"""Phase 4 测试：日志系统（格式/三类文件/滚动/读取）。

日志模块在 import 时按 PKA_LOG_DIR 建 handler，因此用子进程 + 临时目录验证真实行为。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

SCRIPT = """
import sys
sys.path.insert(0, r"{src}")

from pka.logger import error_logger, list_log_files, op_logger, tail_log, update_logger

op_logger.info("入库成功: a.md 块数=3", extra={{"module_name": "ingestion"}})
update_logger.info("更迭评估: decision=REPLACE", extra={{"module_name": "update_agent"}})
error_logger.error("模型调用失败", extra={{"module_name": "qa_agent"}})

print("FILES:", sorted(p.name for p in list_log_files()))
lines = tail_log("operation.log", 5)
print("TAIL_LEN:", len(lines))
print("TAIL_LAST:", lines[-1] if lines else "")

import logging
lg = logging.getLogger("pka.operation:operation.log")
fh = [h for h in lg.handlers if hasattr(h, "doRollover")][0]
fh.doRollover()
print("AFTER_ROLL:", sorted(p.name for p in list_log_files()))
"""


def _run(tmp_path: Path) -> str:
    script = tmp_path / "_log_probe.py"
    script.write_text(SCRIPT.format(src=str(SRC)), encoding="utf-8")
    env = {**os.environ, "PKA_LOG_DIR": str(tmp_path / "logs"), "PKA_DATA_DIR": str(tmp_path / "data"),
           "PYTHONIOENCODING": "utf-8"}
    out = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", env=env, timeout=120)
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_three_log_files_created(tmp_path):
    out = _run(tmp_path)
    assert "operation.log" in out and "update.log" in out and "error.log" in out


def test_log_line_format_matches_prd(tmp_path):
    _run(tmp_path)
    logs = tmp_path / "logs"
    pattern = re.compile(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] \[(INFO|ERROR|WARNING|DEBUG)\] \[\w+\] .+")
    for name in ("operation.log*", "update.log*", "error.log*"):
        files = sorted(logs.glob(name))
        assert files, f"{name} 不存在"
        # operation.log 在探针末尾被 doRollover 改名成 operation.log.YYYY-MM-DD
        lines = [l for l in files[-1].read_text(encoding="utf-8").splitlines() if l.strip()]
        assert lines, f"{name} 为空"
        assert pattern.match(lines[0]), f"{name} 格式不符: {lines[0]}"


def test_error_log_records_module(tmp_path):
    _run(tmp_path)
    txt = (tmp_path / "logs" / "error.log").read_text(encoding="utf-8")
    assert "[ERROR]" in txt and "[qa_agent]" in txt


def test_tail_log_returns_lines(tmp_path):
    out = _run(tmp_path)
    m = re.search(r"TAIL_LEN: (\d+)", out)
    assert m and int(m.group(1)) >= 1


def test_rollover_creates_dated_backup(tmp_path):
    out = _run(tmp_path)
    after = re.search(r"AFTER_ROLL: (.+)", out)
    assert after, out
    names = after.group(1)
    assert re.search(r"operation\.log\.\d{4}-\d{2}-\d{2}", names), names
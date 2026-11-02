"""日志系统（PRD 3.2.5）

三类日志分开存储，均按日期滚动：
  - operation.log：文件上传、入库、删除、模型切换等操作
  - update.log   ：技术更迭评估结果（决策、理由、评分）
  - error.log    ：系统异常与错误堆栈

统一格式：``[时间戳] [级别] [模块] 消息内容``

用法：
    from pka.logger import op_logger, update_logger, error_logger
    op_logger.info("上传文件 %s", name)
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from .config import get_settings

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(module_name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured: set[str] = set()


class _ModuleFilter(logging.Filter):
    """保证每条记录都带 module_name 字段（handler 层已兜底，这里再保一层）。"""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if not hasattr(record, "module_name"):
            record.module_name = record.name
        return True


def _get_logger(name: str, filename: str, level: int = logging.INFO) -> logging.Logger:
    """按文件名创建/复用一个按天滚动的文件 logger，同时输出到控制台。"""
    key = f"{name}:{filename}"
    logger = logging.getLogger(key)
    if key in _configured:
        return logger

    settings = get_settings()
    settings.log_dir.mkdir(parents=True, exist_ok=True)

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(settings.log_dir / filename),
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
        delay=True,
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(_ModuleFilter())

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.WARNING)  # 控制台只显示警告以上，避免刷屏
    console.setFormatter(formatter)
    console.addFilter(_ModuleFilter())

    logger.addHandler(file_handler)
    logger.addHandler(console)
    _configured.add(key)
    return logger


def _make(name: str, filename: str, level: int = logging.INFO) -> logging.Logger:
    """带模块名的 logger 包装，让 module_name 落到日志行里。"""
    return _get_logger(name, filename, level)


# 三类业务日志
op_logger = _make("pka.operation", "operation.log", logging.INFO)
update_logger = _make("pka.update", "update.log", logging.INFO)
error_logger = _make("pka.error", "error.log", logging.ERROR)

# 通用应用日志（开发排查用，写 operation.log 之外的单文件，避免污染业务日志）
app_logger = _make("pka.app", "app.log", logging.DEBUG)


def set_log_module(logger: logging.Logger, module_name: str) -> logging.LoggerAdapter:
    """给 logger 绑定模块标签，返回 adapter，日志行里显示为 [模块]。"""
    return logging.LoggerAdapter(logger, {"module_name": module_name})


def log_exception(module: str, exc: BaseException, context: str = "") -> None:
    """统一记录异常（含堆栈）到 error.log。"""
    msg = f"{context} :: {type(exc).__name__}: {exc}" if context else f"{type(exc).__name__}: {exc}"
    error_logger.error(msg, exc_info=exc, extra={"module_name": module})


def tail_log(filename: str, lines: int = 200) -> list[str]:
    """读取日志文件末尾若干行（前端「日志查看」页用）。"""
    settings = get_settings()
    path = settings.log_dir / filename
    if not path.exists():
        # 还没写过日志时 TimedRotatingFileHandler(delay=True) 不会创建文件
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.readlines()
        return [ln.rstrip("\n") for ln in content[-lines:]]
    except OSError:
        return []


def list_log_files() -> list[Path]:
    """列出 logs/ 目录下所有日志文件（含滚动归档），按修改时间倒序。"""
    settings = get_settings()
    if not settings.log_dir.exists():
        return []
    files = [p for p in settings.log_dir.iterdir() if p.is_file() and p.suffix == ".log" or ".log." in p.name]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
"""统一日志模块，支持动态设置日志等级"""

import logging
import sys

_logger: logging.Logger | None = None
_current_level: str = "error"  # 默认只输出 error


def init_logger(level: str = "error") -> logging.Logger:
    """初始化全局 logger，level 为 'debug' 或 'error'"""
    global _logger, _current_level
    _current_level = level

    _logger = logging.getLogger("heaven")
    _logger.setLevel(_resolve_level(level))

    if not _logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(
            "[%(asctime)s] %(levelname)-5s %(name)s %(filename)s:%(lineno)d | %(message)s",
            datefmt="%H:%M:%S",
        ))
        _logger.addHandler(handler)

    return _logger


def get_logger(name: str = "") -> logging.Logger:
    """获取 logger 实例"""
    global _logger
    if _logger is None:
        _logger = init_logger()
    if name:
        return _logger.getChild(name)
    return _logger


def set_level(level: str):
    """动态设置日志等级（'debug' / 'error'）"""
    global _logger, _current_level
    _current_level = level
    if _logger is not None:
        _logger.setLevel(_resolve_level(level))
        for handler in _logger.handlers:
            handler.setLevel(_resolve_level(level))


def get_level() -> str:
    """获取当前日志等级"""
    return _current_level


def _resolve_level(level: str) -> int:
    """将 'debug' / 'error' 转为 logging 等级"""
    return logging.DEBUG if level == "debug" else logging.ERROR

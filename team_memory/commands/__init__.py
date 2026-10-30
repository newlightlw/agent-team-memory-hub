"""team-memory CLI 命令实现。"""

from .bridges_doctor_cmd import bridges_doctor_cmd
from .capture_cmd import capture_cmd
from .doctor_cmd import doctor_cmd
from .inbox_cmd import approve_cmd, decline_cmd, propose_cmd, review_cmd
from .init_cmd import init_cmd
from .index_cmd import index_cmd
from .list_cmd import list_cmd, show_cmd
from .load_cmd import load_cmd
from .save_cmd import save_cmd
from .sync_cmd import sync_cmd
from .update_cmd import update_cmd
from .validate_cmd import validate_cmd
from .web_cmd import web_cmd

__all__ = [
    "init_cmd",
    "capture_cmd",
    "save_cmd",
    "load_cmd",
    "sync_cmd",
    "list_cmd",
    "show_cmd",
    "web_cmd",
    "update_cmd",
    "doctor_cmd",
    "bridges_doctor_cmd",
    "validate_cmd",
    "index_cmd",
    "propose_cmd",
    "review_cmd",
    "approve_cmd",
    "decline_cmd",
]

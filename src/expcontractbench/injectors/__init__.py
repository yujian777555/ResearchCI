"""六个 versioned、只依赖结构后置条件的 mutation injector。"""

from .c001_seed_set import inject as inject_c001
from .c002_budget import inject as inject_c002
from .c003_split import inject as inject_c003
from .c004_config import inject as inject_c004
from .c005_cache import inject as inject_c005
from .c006_failed_run import inject as inject_c006

INJECTORS = {
    "RCI-C001": inject_c001,
    "RCI-C002": inject_c002,
    "RCI-C003": inject_c003,
    "RCI-C004": inject_c004,
    "RCI-C005": inject_c005,
    "RCI-C006": inject_c006,
}

__all__ = ["INJECTORS"]

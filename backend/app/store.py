"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

from typing import Any

from app.seed import SEED_ROWS


class Store:
    # 为同一类协作数据保留常见命名；别名必须指向同一个 list，避免镜像出第二份状态。
    TABLE_ALIASES = {
        "quality_corrections": "quality_correction",
        "quality_report_correction": "quality_correction",
        "quality_report_corrections": "quality_correction",
        "correction_inbox": "quality_correction",
        "quality_correction_receipts": "quality_correction_receipt",
        "import_receipt": "quality_correction_receipt",
        "import_receipts": "quality_correction_receipt",
        "correction_receipt": "quality_correction_receipt",
        "correction_receipts": "quality_correction_receipt",
        "review_todos": "review_todo",
        "review_agenda": "review_todo",
        "review_agenda_todo": "review_todo",
        "review_topic": "review_todo",
        "review_topics": "review_todo",
        "review_issue_todo": "review_todo",
    }

    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        canonical = self.TABLE_ALIASES.get(module, module)
        rows = self._tables.setdefault(canonical, [])
        if module != canonical:
            self._tables[module] = rows
        return rows

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        # 更正回执、议题待办等是质量简报/复盘会议的内部协作表，不额外占业务模块卡片。
        for name in sorted(SEED_ROWS.keys()):
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()

"""复盘议题待办的通用资源服务；写入逻辑仍由质量更正领域服务负责。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.services.quality_correction import (
    TODO_TABLE,
    quality_correction_service,
)
from app.store import store


class ReviewTodoService(BaseModuleService):
    MODULE = TODO_TABLE
    ENTITY = "复盘议题待办"
    LIST_FIELDS = ["title", "report_no", "覆盖学期", "编制部门", "签收人", "meeting_id", "status", "source_ref"]
    REQUIRED_FIELDS: list[str] = []
    STATUS_ORDER = ["待主持人核对更正版", "可随已签认议程分发，更正另办", "已列入议程", "已完成"]
    ACTION_RULES: dict[str, str] = {}

    def run_action(
        self,
        entry_id: int,
        action: str,
        payload: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        todo = store.find(self.MODULE, entry_id)
        if todo is None:
            return None, f"复盘议题待办 {entry_id} 不存在"
        meeting_id = todo.get("meeting_id")
        if meeting_id is None:
            return None, "该议题尚未关联复盘会议"

        from app.services.review_meeting import ReviewMeetingService

        meeting_service = ReviewMeetingService()
        if action in ("核对更正版后分发", "按更正版分发", "核对并分发"):
            meeting, message = meeting_service.run_action(
                int(meeting_id), "核对更正版后分发", payload or {}
            )
            return (todo if meeting is not None else None), message
        if action in ("核对更正版", "确认更正议程", "核对"):
            meeting, message = quality_correction_service.verify_corrected_agenda(int(meeting_id))
            return (todo if meeting is not None else None), message
        if action in ("分发", "分发给教师", "分发议题", "主持人分发"):
            meeting, message = meeting_service.run_action(
                int(meeting_id), "分发给教师", payload or {}
            )
            return (todo if meeting is not None else None), message
        return None, f"动作「{action}」不属于复盘议题待办可执行范围"

"""复盘会议领域服务：会议纪要登记、签认、分发，含跨模块决议分发到诊改任务。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.services.quality_correction import (
    capture_agenda_snapshot,
    now_text,
    quality_correction_service,
)
from app.store import store


class ReviewMeetingService(BaseModuleService):
    MODULE = "review_meeting"
    ENTITY = "会议纪要"
    OPERATION_TERM = "签认纪要"
    LIST_FIELDS = ["会议主题", "参会人员", "召开日期", "决议事项", "分歧观点", "记录人员", "下次会议", "备注说明", "meeting_no", "覆盖学期", "学期", "期次", "复盘期次", "期号"]
    REQUIRED_FIELDS = ["会议主题", "参会人员", "召开日期"]
    STATUS_ORDER = ["草稿", "待签认", "已签认", "已分发"]
    ACTION_RULES = {
        "签认纪要": "已签认",
        "提出异议": "草稿",
        "分发给教师": "已分发",
        "召开会议": "已召开",
    }
    NEGATIVE_ACTIONS = []

    def run_action(
        self,
        entry_id: int,
        action: str,
        payload: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """执行动作，含跨模块联动：分发时创建关联诊改任务。"""
        entry = self.get_entry(entry_id)
        if entry is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"
        payload = payload or {}

        if action in ("核对更正版", "确认更正议程", "核对更正", "确认更正版"):
            return quality_correction_service.verify_corrected_agenda(
                entry_id,
                verifier=str(payload.get("verifier") or payload.get("主持人") or ""),
                remark=str(payload.get("remark") or ""),
            )

        if action in ("核对更正版后分发", "按更正版分发", "核对更正版并分发", "确认后分发"):
            return quality_correction_service.verify_corrected_agenda(
                entry_id,
                verifier=str(payload.get("verifier") or payload.get("主持人") or ""),
                distribute=True,
            )

        if action in ("分发", "分发纪要", "下发给教师"):
            action = "分发给教师"

        # 签认纪要先通过待签认状态
        if action == "签认纪要":
            if entry.get("status") not in ("待签认", "草稿"):
                return None, f"{self.ENTITY} {entry_id} 当前状态为'{entry.get('status')}'，不可签认"

        if action == "召开会议":
            if entry.get("status") not in ("已分发", "已签认"):
                return None, f"{self.ENTITY} {entry_id} 必须先完成分发或签认，才能登记召开"
            entry["status"] = "已召开"
            entry["pending"] = False
            entry["held_at"] = entry.get("held_at") or now_text()
            capture_agenda_snapshot(entry, "held_agenda_snapshot")
            return entry, f"{self.ENTITY} {entry_id} 已召开，当时带入的议题依据已冻结"

        # 分发给教师：必须先签认；若有影响议程的新更正，先给主持人明确判定。
        if action == "分发给教师":
            if entry.get("status") == "已召开" or entry.get("held_at"):
                readiness = quality_correction_service.distribution_readiness(entry)
                return None, (readiness or {}).get("headline", "会议已召开，议题依据已冻结")
            if entry.get("status") != "已签认":
                return None, f"{self.ENTITY} {entry_id} 必须先签认纪要，才能分发"

            readiness = quality_correction_service.distribution_readiness(entry)
            if readiness and not readiness["can_distribute"]:
                entry["distribution_readiness"] = readiness
                entry["distribution_decision"] = readiness["decision"]
                entry["distribution_mode"] = readiness["mode"]
                entry["can_distribute"] = False
                return None, readiness["headline"]

        result_entry, message = super().run_action(entry_id, action)

        # 签认时冻结旧议题依据，后续导入更正不会改写该快照。
        if result_entry and action == "签认纪要":
            result_entry["meeting_no"] = result_entry.get("meeting_no") or f"HY-{result_entry['id']:04d}"
            capture_agenda_snapshot(result_entry, "signed_agenda_snapshot")

        # 分发给教师时，检查决议事项是否需要创建诊改任务
        if result_entry and action == "分发给教师":
            readiness = quality_correction_service.distribution_readiness(result_entry)
            if readiness:
                result_entry["distribution_mode"] = readiness["mode"]
                result_entry["distribution_decision"] = readiness["decision"]
                result_entry["distribution_readiness"] = readiness
                result_entry["can_distribute"] = True
                message = f"{message}；{readiness['headline']}"
            capture_agenda_snapshot(result_entry, "distribution_agenda_snapshot")
            resolution = entry.get("决议事项", "")
            meeting_theme = entry.get("会议主题", "")
            if resolution and "任务" in str(resolution):
                self._maybe_create_improve_task(meeting_theme, resolution, entry_id)

        return result_entry, message

    def distribution_readiness(self, entry_id: int):
        return quality_correction_service.distribution_readiness(entry_id)

    def _maybe_create_improve_task(self, theme: str, resolution: str, meeting_id: int) -> None:
        """根据会议决议创建诊改任务：幂等保护，不重复创建。"""
        task_rows = store.rows("improve_task")
        # 幂等检查
        for row in task_rows:
            existing_desc = str(row.get("任务描述", ""))
            if f"meeting:{meeting_id}" in existing_desc:
                return

        new_id = max((int(r.get("id", 0)) for r in task_rows), default=0) + 1
        task_rows.append({
            "id": new_id,
            "任务描述": f"会议决议：{theme} [meeting:{meeting_id}]",
            "承接方案": resolution,
            "执行人员": "",
            "起止日期": "",
            "验收标准": "",
            "督办人员": "",
            "任务权重": "",
            "备注说明": "由复盘会议决议自动生成",
            "status": "待认领",
            "pending": True,
            "abnormal": False,
        })

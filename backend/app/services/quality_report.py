"""质量简报领域服务：简报登记、签收、传达，含更正收件与跨模块复盘联动。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.services.quality_correction import QualityCorrectionService
from app.store import store


class QualityReportService(BaseModuleService):
    MODULE = "quality_report"
    ENTITY = "质量简报"
    OPERATION_TERM = "签收简报"
    LIST_FIELDS = ["覆盖学期", "教学质量概况", "突出问题", "改进方向", "编制部门", "发布日期", "发放范围", "备注说明", "简报编号", "编号", "报告编号", "学期", "签收人", "签收部门", "接收人"]
    REQUIRED_FIELDS = ["覆盖学期", "教学质量概况", "突出问题"]
    STATUS_ORDER = ["草稿", "待签收", "已签收", "已传达"]
    ACTION_RULES = {"签收简报": "已签收", "补充说明": "草稿", "传达到教师": "已传达"}
    NEGATIVE_ACTIONS = []

    def __init__(self) -> None:
        self.corrections = QualityCorrectionService()

    # ---------- 更正收件/回执的兼容入口 ----------
    def import_corrections(self, *args: Any, **kwargs: Any):
        return self.corrections.import_corrections(*args, **kwargs)

    def import_correction_file(self, *args: Any, **kwargs: Any):
        return self.corrections.import_corrections(*args, **kwargs)

    upload_correction_file = import_correction_file
    receive_correction_file = import_correction_file

    def get_receipt(self, receipt_ref: int | str):
        return self.corrections.get_receipt(receipt_ref)

    def download_receipt(self, receipt_ref: int | str):
        return self.corrections.download_receipt(receipt_ref)

    def resume_receipt(self, *args: Any, **kwargs: Any):
        return self.corrections.resume_receipt(*args, **kwargs)

    complete_receipt = resume_receipt
    continue_receipt = resume_receipt

    def sign_correction(self, *args: Any, **kwargs: Any):
        return self.corrections.sign_correction(*args, **kwargs)

    def run_action(self, entry_id: int, action: str, payload: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, str]:
        """执行动作，含跨模块联动：签收时检查突出问题触发复盘会议。"""
        entry = self.get_entry(entry_id)
        if entry is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"

        # 更正行的签收入口：/api/quality_report/{id}/actions 或带 correction_id 的动作均可。
        if action in ("签收更正", "确认更正", "确认更正并同步", "签收"):
            correction_id = (payload or {}).get("correction_id") or (payload or {}).get("更正ID")
            signer = str((payload or {}).get("signer") or (payload or {}).get("签收人") or "")
            if correction_id:
                return self.corrections.sign_correction(
                    correction_id,
                    signer=signer,
                    remark=str((payload or {}).get("remark") or ""),
                )
            signed, message = self.corrections.sign_pending_for_report(entry_id, signer)
            return (entry, message) if signed else (None, message)

        # 签收简报的幂等保护
        if action == "签收简报":
            if entry.get("status") == "已签收":
                return None, f"{self.ENTITY} {entry_id} 已是已签收状态，无需重复签收"

        # 传达到教师：必须先签收
        if action == "传达到教师":
            if entry.get("status") != "已签收":
                return None, f"{self.ENTITY} {entry_id} 必须先签收简报，才能传达"

        result_entry, message = super().run_action(entry_id, action)

        # 签收简报后，如果突出问题中存在严重问题，触发复盘会议
        if result_entry and action == "签收简报":
            problem = entry.get("突出问题", "")
            semester = entry.get("覆盖学期", "")
            if problem and ("严重" in str(problem) or "预警" in str(problem)):
                self._maybe_create_review_meeting(semester, problem, entry_id)
            signed_corrections, correction_message = self.corrections.sign_pending_for_report(entry_id)
            if signed_corrections:
                message = f"{message}；{correction_message}"

        return result_entry, message

    def _maybe_create_review_meeting(
        self, semester: str, problem: str, report_id: int
    ) -> None:
        """简报中存在严重问题时，自动触发复盘会议。"""
        meeting_rows = store.rows("review_meeting")
        # 幂等检查：同一简报不重复触发；同一学期/期次也只保留一场复盘。
        for row in meeting_rows:
            existing_source = str(row.get("决议事项", ""))
            if f"quality_report:{report_id}" in existing_source:
                return
            if semester and (
                str(row.get("覆盖学期", "")) == semester
                or str(row.get("期次", "")) == semester
                or semester in str(row.get("会议主题", ""))
            ):
                if f"quality_report:{report_id}" not in existing_source:
                    row["决议事项"] = (
                        existing_source + f"；补充简报问题 [quality_report:{report_id}]"
                    ).strip("；")
                return

        new_id = max((int(r.get("id", 0)) for r in meeting_rows), default=0) + 1
        meeting_rows.append({
            "id": new_id,
            "meeting_no": f"HY-{new_id:04d}",
            "会议主题": f"{semester}学期质量简报突出问题复盘",
            "参会人员": "教研室主任、相关教师",
            "召开日期": "",
            "决议事项": f"针对简报中问题制定整改决议 [quality_report:{report_id}]",
            "分歧观点": "",
            "记录人员": "",
            "下次会议": "",
            "备注说明": "由质量简报签收后自动生成",
            "覆盖学期": semester,
            "期次": semester,
            "status": "待签认",
            "pending": True,
            "abnormal": False,
        })

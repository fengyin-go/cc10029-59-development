"""质量简报更正收件、回执、签收同步和复盘分发约束。"""
import csv
import io

from app.services.quality_report import QualityReportService
from app.services.review_meeting import ReviewMeetingService
from app.store import store


def clear_all():
    for name in store.module_names():
        store.rows(name).clear()


def make_report(svc, code, department, semester="2026-春季", problem="旧议题"):
    report, _ = svc.create_entry({
        "简报编号": code,
        "覆盖学期": semester,
        "教学质量概况": "概况",
        "突出问题": problem,
        "编制部门": department,
        "签收人": "李督导",
    })
    return report


class TestQualityCorrectionImport:
    def setup_method(self):
        clear_all()
        self.svc = QualityReportService()
        self.a = make_report(self.svc, "Q-15", "A系")
        self.b = make_report(self.svc, "Q-16", "教务处")

    def test_import_matches_original_number_and_rejects_cross_department_update(self):
        content = (
            "原简报编号,编制部门,突出问题,更正说明\n"
            "Q-16,教务处,新的预警问题,本部门更正\n"
            "Q-15,教务处,串改A系,应被部门拦截\n"
            "Q-999,不存在部门,找不到编号,无效\n"
        )
        receipt, message = self.svc.import_corrections(content=content, filename="c.csv")

        assert receipt is not None
        assert receipt["valid_count"] == 1
        assert receipt["invalid_count"] == 2
        assert len(receipt["items"]) == 3

        valid = next(item for item in receipt["items"] if item["valid"])
        assert valid["report_no"] == "Q-16"
        assert valid["quality_report_id"] == self.b["id"]
        assert valid["status"] == "待签收"

        invalid_cross = next(item for item in receipt["items"] if item["原简报编号"] == "Q-15")
        assert invalid_cross["valid"] is False
        assert "不能由" in invalid_cross["message"]
        assert store.find("quality_report", self.a["id"])["突出问题"] == "旧议题"

        invalid_missing = next(item for item in receipt["items"] if item["原简报编号"] == "Q-999")
        assert invalid_missing["valid"] is False
        assert "Q-999" in invalid_missing["message"]

        # 导入后、签收前不直接覆盖原简报。
        assert store.find("quality_report", self.b["id"])["突出问题"] == "旧议题"
        assert "JC-" in message

    def test_receipt_csv_keeps_original_number_for_invalid_rows(self):
        receipt, _ = self.svc.import_corrections(rows=[
            {"原简报编号": "Q-404", "编制部门": "X", "更正说明": "找不到"},
        ])
        csv_text = self.svc.download_receipt(receipt["id"])
        rows = list(csv.DictReader(io.StringIO(csv_text.lstrip("﻿"))))
        assert rows[0]["原简报编号"] == "Q-404"
        assert rows[0]["是否有效"] == "否"
        assert rows[0]["问题说明"]

    def test_resume_original_receipt_is_idempotent_and_keeps_one_meeting(self):
        content = "原简报编号,编制部门,更正类型,突出问题\nQ-16,教务处,实质性,新的严重预警\n"
        receipt, _ = self.svc.import_corrections(content=content)
        item = next(item for item in receipt["items"] if item["valid"])
        self.svc.sign_correction(item["id"])
        assert len(store.rows("review_meeting")) == 1

        resumed, message = self.svc.resume_receipt(receipt["receipt_no"], content=content)
        assert resumed["id"] == receipt["id"]
        assert "未重复导入" in message
        assert resumed["total_rows"] == 1
        assert len(store.rows("review_meeting")) == 1

        extra = "原简报编号,编制部门,更正类型,更正说明\nQ-16,教务处,文字更正,补充标点\n"
        completed, _ = self.svc.resume_receipt(receipt["receipt_no"], content=extra)
        assert completed["total_rows"] == 2
        assert len(store.rows("review_meeting")) == 1


class TestMeetingDistributionAndHistory:
    def setup_method(self):
        clear_all()
        self.reports = QualityReportService()
        self.meetings = ReviewMeetingService()
        self.report = make_report(self.reports, "Q-16", "教务处")
        meeting, _ = self.meetings.create_entry({
            "会议主题": "2026-春季复盘",
            "参会人员": "督导",
            "召开日期": "2026-11-20",
            "决议事项": "讨论 Q-16 旧议题",
            "覆盖学期": "2026-春季",
        })
        self.meeting_id = meeting["id"]
        self.meetings.run_action(self.meeting_id, "签认纪要")

    def import_and_sign_major(self):
        receipt, _ = self.reports.import_corrections(content=(
            "原简报编号,编制部门,更正类型,突出问题\n"
            "Q-16,教务处,实质性更正,更正后的严重预警问题\n"
        ))
        correction = next(item for item in receipt["items"] if item["valid"])
        self.reports.sign_correction(correction["id"], "李督导")
        return correction

    def test_major_correction_requires_corrected_version_check_before_distribution(self):
        correction = self.import_and_sign_major()
        todo_rows = store.rows("review_todo")
        assert any(row["source_ref"] == f"quality_correction:{correction['id']}" for row in todo_rows)

        blocked, message = self.meetings.run_action(self.meeting_id, "分发给教师")
        assert blocked is None
        assert "核对更正版" in message

        distributed, ok_message = self.meetings.run_action(self.meeting_id, "核对更正版后分发")
        assert distributed is not None
        assert distributed["status"] == "已分发"
        assert "更正版" in ok_message
        assert store.find("quality_report", self.report["id"])["突出问题"] == "更正后的严重预警问题"

    def test_minor_correction_can_continue_signed_agenda_and_handle_separately(self):
        receipt, _ = self.reports.import_corrections(content=(
            "原简报编号,编制部门,更正类型,发放范围\n"
            "Q-16,教务处,文字更正,全体任课教师（订正联系方式）\n"
        ))
        correction = next(item for item in receipt["items"] if item["valid"])
        self.reports.sign_correction(correction["id"])

        entry, message = self.meetings.run_action(self.meeting_id, "分发给教师")
        assert entry is not None
        assert entry["status"] == "已分发"
        assert "沿已签认议程继续" in message
        assert correction["id"] in entry["distribution_readiness"]["separate_correction_ids"]

    def test_held_meeting_keeps_original_topic_basis_after_later_correction(self):
        self.meetings.run_action(self.meeting_id, "召开会议")
        held = store.find("review_meeting", self.meeting_id)
        old_snapshot = held["held_agenda_snapshot"]

        self.import_and_sign_major()
        held_after = store.find("review_meeting", self.meeting_id)
        assert held_after["held_agenda_snapshot"] == old_snapshot
        readiness = self.meetings.distribution_readiness(self.meeting_id)
        assert readiness["mode"] == "historical_meeting_basis_locked"
        assert readiness["historical_basis_preserved"] is True

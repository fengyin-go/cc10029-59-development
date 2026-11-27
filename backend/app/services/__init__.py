"""领域服务注册表：通用资源路由按模块 key 分派到独立业务服务。"""
from __future__ import annotations

from app.services.base import BaseModuleService
from app.services.observation import ObservationService
from app.services.feedback import FeedbackService
from app.services.improve_plan import ImprovePlanService
from app.services.progress_log import ProgressLogService
from app.services.peer_review import PeerReviewService
from app.services.teach_record import TeachRecordService
from app.services.semester_goal import SemesterGoalService
from app.services.review_meeting import ReviewMeetingService
from app.services.review_todo import ReviewTodoService
from app.services.improve_task import ImproveTaskService
from app.services.external_eval import ExternalEvalService
from app.services.course_group import CourseGroupService
from app.services.syllabus_rev import SyllabusRevService
from app.services.teach_award import TeachAwardService
from app.services.lesson_prep import LessonPrepService
from app.services.mentor_pair import MentorPairService
from app.services.exam_analysis import ExamAnalysisService
from app.services.class_schedule import ClassScheduleService
from app.services.resource_apply import ResourceApplyService
from app.services.quality_report import QualityReportService
from app.services.quality_correction import QualityCorrectionService
from app.services.quality_import import QualityImportService
from app.services.import_receipt import ImportReceiptService
from app.services.textbook_select import TextbookSelectService

SERVICES: dict[str, BaseModuleService] = {
    "observation": ObservationService(),
    "feedback": FeedbackService(),
    "improve_plan": ImprovePlanService(),
    "progress_log": ProgressLogService(),
    "peer_review": PeerReviewService(),
    "teach_record": TeachRecordService(),
    "semester_goal": SemesterGoalService(),
    "review_meeting": ReviewMeetingService(),
    "review_todo": ReviewTodoService(),
    "review_agenda": ReviewTodoService(),
    "improve_task": ImproveTaskService(),
    "external_eval": ExternalEvalService(),
    "course_group": CourseGroupService(),
    "syllabus_rev": SyllabusRevService(),
    "teach_award": TeachAwardService(),
    "lesson_prep": LessonPrepService(),
    "mentor_pair": MentorPairService(),
    "exam_analysis": ExamAnalysisService(),
    "class_schedule": ClassScheduleService(),
    "resource_apply": ResourceApplyService(),
    "quality_report": QualityReportService(),
    "quality_correction": QualityCorrectionService(),
    "quality_corrections": QualityCorrectionService(),
    "quality_import": QualityImportService(),
    "quality_report_correction": QualityCorrectionService(),
    "quality_report_corrections": QualityCorrectionService(),
    "correction_inbox": QualityCorrectionService(),
    "import_receipt": ImportReceiptService(),
    "import_receipts": ImportReceiptService(),
    "correction_receipt": ImportReceiptService(),
    "correction_receipts": ImportReceiptService(),
    "quality_correction_receipt": ImportReceiptService(),
    "textbook_select": TextbookSelectService(),
}


def service_for(module: str) -> BaseModuleService | None:
    return SERVICES.get(module)

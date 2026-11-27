"""兼容命名：复盘议程/议题待办服务。"""
from app.services.quality_correction import (
    capture_agenda_snapshot,
    ensure_review_meeting,
    quality_correction_service,
)
from app.services.review_todo import ReviewTodoService


class ReviewAgendaService(ReviewTodoService):
    def distribution_readiness(self, meeting_ref):
        return quality_correction_service.distribution_readiness(meeting_ref)

    def capture_snapshot(self, meeting, label: str = "signed_agenda_snapshot"):
        return capture_agenda_snapshot(meeting, label)


__all__ = [
    "ReviewAgendaService",
    "capture_agenda_snapshot",
    "ensure_review_meeting",
    "quality_correction_service",
]

"""导入回执的通用只读资源服务；导入/续传逻辑在质量更正服务中。"""
from __future__ import annotations

from app.services.base import BaseModuleService
from app.services.quality_correction import (
    RECEIPT_TABLE,
    quality_correction_service,
)


class ImportReceiptService(BaseModuleService):
    MODULE = RECEIPT_TABLE
    ENTITY = "导入回执"
    LIST_FIELDS = ["receipt_no", "filename", "编制部门", "status", "total_rows", "valid_count", "invalid_count"]
    REQUIRED_FIELDS: list[str] = []
    STATUS_ORDER = ["处理中", "待签收", "部分有效", "含无效行", "已签收"]
    ACTION_RULES: dict[str, str] = {}

    def download_receipt(self, receipt_ref: int | str) -> str | None:
        return quality_correction_service.download_receipt(receipt_ref)

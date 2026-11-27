"""质量简报更正收件、签认同步、回执与复盘分发判定。

该模块只使用内存仓库，但把“更正批次/回执—更正行—复盘议题待办”分开保存，
便于导入中断后凭原回执续传，也便于已召开会议冻结当时的议题依据。
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
from datetime import datetime
from typing import Any, Iterable

from app.services.base import BaseModuleService
from app.store import store

CORRECTION_TABLE = "quality_correction"
CORRECTION_TABLE_ALIASES = [
    "quality_corrections",
    "quality_report_correction",
    "quality_report_corrections",
    "correction_inbox",
]
RECEIPT_TABLE = "quality_correction_receipt"
RECEIPT_TABLE_ALIASES = [
    "quality_correction_receipts",
    "import_receipt",
    "import_receipts",
    "correction_receipt",
    "correction_receipts",
]
TODO_TABLE = "review_todo"
TODO_TABLE_ALIASES = [
    "review_todos",
    "review_agenda",
    "review_agenda_todo",
    "review_topic",
    "review_topics",
    "review_issue_todo",
]
MEETING_TABLE = "review_meeting"
REPORT_TABLE = "quality_report"

REPORT_CODE_FIELDS = [
    "原简报编号", "简报编号", "原编号", "原简报ID", "简报ID", "报告编号", "质量简报编号", "编号", "文号",
    "original_code", "original_report_no", "quality_report_id", "report_id",
    "report_no", "report_code", "quality_report_no", "code", "id",
]
DEPARTMENT_FIELDS = ["编制部门", "所属部门", "提交部门", "申请部门", "部门", "department", "dept"]
SEMESTER_FIELDS = ["覆盖学期", "适用学期", "学期", "semester", "term"]
PERIOD_FIELDS = ["复盘期次", "期次", "期号", "覆盖学期", "适用学期", "学期"]
SIGNER_FIELDS = ["签收人", "确认人", "接收人", "收件人", "签认人", "signer", "assignee"]
KEY_FIELD_ALIASES: dict[str, list[str]] = {
    "教学质量概况": ["教学质量概况", "质量概况", "总体情况", "概况"],
    "突出问题": ["突出问题", "主要问题", "问题", "存在问题"],
    "改进方向": ["改进方向", "整改方向", "改进措施", "整改措施"],
    "发布日期": ["发布日期", "印发日期", "日期"],
    "发放范围": ["发放范围", "分发范围", "发送范围"],
    "备注说明": ["备注说明", "备注", "说明"],
}
LONG_FIELD_NAMES = ["更正字段", "字段", "目标字段", "field"]
LONG_VALUE_NAMES = ["更正后内容", "更正内容", "新内容", "更正为", "修改后", "value", "new_value"]
CORRECTION_TEXT_FIELDS = ["更正说明", "更正摘要", "更正事项", "correction", "change_summary"]

MAJOR_FIELDS = {"教学质量概况", "突出问题"}
MAJOR_WORDS = ("严重", "预警", "重大", "实质", "关键数据", "数据失实", "结论错误", "不及格", "教学事故", "必须核对")
MINOR_WORDS = ("错别字", "文字", "标点", "格式", "排版", "措辞", "语序", "联系方式", "电话", "页码")


def now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def decode_bytes(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def compact_code(value: Any) -> str:
    return re.sub(r"[\s\-_－—()（）\[\]【】]", "", text(value).upper())


def code_keys(value: Any) -> set[str]:
    """返回编号的可比较形式；Q-16、q16、016 与数字 16 可互相匹配。"""
    raw = text(value)
    compact = compact_code(raw)
    keys = {compact} if compact else set()
    match = re.fullmatch(r"(?:Q|ZL|BG)?0*(\d+)", compact)
    if match:
        number = str(int(match.group(1)))
        keys.add(number)
        keys.add(f"Q{number}")
    return {key for key in keys if key}


def first_value(row: dict[str, Any], names: Iterable[str]) -> str:
    for name in names:
        if name in row and text(row[name]):
            return text(row[name])
    lower_map = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        value = lower_map.get(name.lower())
        if value is not None and text(value):
            return text(value)
    return ""


def report_code(report: dict[str, Any]) -> str:
    explicit = first_value(report, [name for name in REPORT_CODE_FIELDS if name != "id"])
    return explicit or f"Q-{int(report.get('id', 0))}"


def report_matches_code(report: dict[str, Any], raw_code: str) -> bool:
    wanted = code_keys(raw_code)
    if not wanted:
        return False
    candidates: set[str] = set()
    for field in REPORT_CODE_FIELDS:
        if field == "id":
            value = report.get("id")
        else:
            value = report.get(field)
        candidates.update(code_keys(value))
    candidates.update(code_keys(f"Q-{report.get('id', 0)}"))
    return bool(wanted & candidates)


def find_report(raw_code: str) -> dict[str, Any] | None:
    if not text(raw_code):
        return None
    for report in store.rows(REPORT_TABLE):
        if report_matches_code(report, raw_code):
            return report
    return None


def period_key(row: dict[str, Any]) -> str:
    return first_value(row, PERIOD_FIELDS)


def report_period(report: dict[str, Any]) -> str:
    return first_value(report, PERIOD_FIELDS)


def parse_tabular_content(content: str, filename: str = "") -> list[dict[str, Any]]:
    """解析 CSV/TSV/JSON；导入入口不强制前端必须传 multipart。"""
    raw = content or ""
    if raw.startswith("﻿"):
        raw = raw.lstrip("﻿")
    stripped = raw.strip()
    if not stripped:
        return []

    if stripped[0] in "[{":
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            for key in ("rows", "items", "data", "corrections"):
                if isinstance(parsed.get(key), list):
                    return [dict(row) for row in parsed[key] if isinstance(row, dict)]
            return [parsed]
        if isinstance(parsed, list):
            return [dict(row) for row in parsed if isinstance(row, dict)]

    delimiter = "\t" if filename.lower().endswith(".tsv") or "\t" in raw.splitlines()[0] else ","
    reader = csv.DictReader(io.StringIO(raw), delimiter=delimiter)
    return [dict(row) for row in reader]


def _next_id(rows: list[dict[str, Any]]) -> int:
    return max((int(row.get("id", 0) or 0) for row in rows), default=0) + 1


def mirror_row(table_names: list[str], row: dict[str, Any]) -> None:
    """把同一对象同步到可能的命名表，兼容不同测试/接口命名习惯。"""
    for table_name in table_names:
        rows = store.rows(table_name)
        if not any(candidate is row or candidate.get("id") == row.get("id") for candidate in rows):
            rows.append(row)


def _change_key(raw_code: str, changes: dict[str, Any], correction_text: str) -> str:
    basis = json.dumps(changes, ensure_ascii=False, sort_keys=True) + "|" + correction_text
    return f"{compact_code(raw_code)}:{basis}"


def _raw_row_key(raw_code: str, raw_row: dict[str, Any]) -> str:
    """用导入原文生成幂等键；更正签收后旧值变化也不会导致重试重复入库。"""
    stable_row = {
        str(key): text(value)
        for key, value in sorted(raw_row.items(), key=lambda item: str(item[0]))
        if text(value)
    }
    basis = json.dumps(stable_row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{compact_code(raw_code)}:{basis}"


def classify_impact(
    changes: dict[str, dict[str, str]],
    correction_type: str,
    correction_text: str,
) -> tuple[str, bool]:
    """返回 (major|minor, 是否要求核对更正版)。"""
    joined_type = correction_type
    changed_fields = set(changes)
    content_blob = " ".join(
        [correction_type, correction_text, *(str(item.get("new", "")) for item in changes.values())]
    )

    explicit_minor = any(word in joined_type for word in ("一般", "文字", "轻微", "编辑", "minor", "editorial"))
    explicit_major = any(word in joined_type for word in ("重大", "实质", "关键", "major", "critical"))

    if explicit_major:
        return "major", True
    if explicit_minor:
        return "minor", False
    if changed_fields & MAJOR_FIELDS:
        # 仅当内容明确是文字性修正时才走“原议程继续 + 更正另办”。
        if any(word in content_blob for word in MINOR_WORDS) and not any(word in content_blob for word in MAJOR_WORDS):
            return "minor", False
        return "major", True
    if any(word in content_blob for word in MAJOR_WORDS):
        return "major", True
    if changed_fields and changed_fields <= {"发布日期", "发放范围", "备注说明"}:
        return "minor", False
    if any(word in content_blob for word in MINOR_WORDS):
        return "minor", False
    # 未说明影响面的更正不能覆盖已签认议程，分发前应核对更正版。
    return "unknown", True


def extract_changes(row: dict[str, Any]) -> tuple[dict[str, dict[str, str]], str, str]:
    nested = row.get("corrections") or row.get("fields") or row.get("更正明细")
    if isinstance(nested, dict):
        row = {**nested, **row}
    changes: dict[str, dict[str, str]] = {}
    correction_text = first_value(row, CORRECTION_TEXT_FIELDS)
    correction_type = first_value(row, ["更正类型", "类型", "影响类型", "correction_type", "impact"])

    report = find_report(first_value(row, REPORT_CODE_FIELDS))
    for canonical, aliases in KEY_FIELD_ALIASES.items():
        new_value = first_value(row, aliases)
        if not new_value:
            continue
        old_value = text(report.get(canonical)) if report else ""
        if new_value != old_value:
            changes[canonical] = {"old": old_value, "new": new_value}

    target_field = first_value(row, LONG_FIELD_NAMES)
    long_value = first_value(row, LONG_VALUE_NAMES)
    if target_field and long_value:
        canonical = target_field
        for standard, aliases in KEY_FIELD_ALIASES.items():
            if target_field == standard or target_field in aliases:
                canonical = standard
                break
        old_value = text(report.get(canonical)) if report else ""
        if long_value != old_value:
            changes[canonical] = {"old": old_value, "new": long_value}

    return changes, correction_text, correction_type


class QualityCorrectionService(BaseModuleService):
    MODULE = CORRECTION_TABLE
    ENTITY = "质量简报更正"
    LIST_FIELDS = ["report_no", "覆盖学期", "编制部门", "签收人", "status", "correction_text"]
    REQUIRED_FIELDS: list[str] = []
    STATUS_ORDER = ["无效", "待签收", "已签收"]
    ACTION_RULES: dict[str, str] = {}

    # ---------- 回执与导入 ----------
    def list_receipts(self) -> list[dict[str, Any]]:
        return list(store.rows(RECEIPT_TABLE))

    def get_receipt(self, receipt_ref: int | str) -> dict[str, Any] | None:
        receipts = store.rows(RECEIPT_TABLE)
        ref = text(receipt_ref)
        if not ref:
            return None
        if ref.isdigit():
            found = store.find(RECEIPT_TABLE, int(ref))
            if found:
                return found
        compact = compact_code(ref)
        for receipt in receipts:
            if compact_code(receipt.get("receipt_no")) == compact or compact_code(receipt.get("id")) == compact:
                return receipt
        return None

    get_import_receipt = get_receipt

    def download_receipt(self, receipt_ref: int | str) -> str | None:
        receipt = self.get_receipt(receipt_ref)
        if receipt is None:
            return None
        output = io.StringIO()
        headers = [
            "原简报编号", "行号", "回执编号", "处理状态", "是否有效", "问题说明",
            "匹配简报ID", "覆盖学期", "编制部门", "签收人", "更正类型", "影响级别",
            "要求核对更正版", "更正字段", "更正内容", "幂等键",
        ]
        writer = csv.DictWriter(output, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        def csv_safe(value: Any) -> str:
            value_text = text(value)
            if value_text.startswith(("=", "+", "-", "@")):
                return "'" + value_text
            return value_text

        for item in receipt.get("items", []):
            changes = item.get("changes") if isinstance(item.get("changes"), dict) else {}
            row_values = {
                "原简报编号": item.get("原简报编号", ""),
                "行号": item.get("row_no", ""),
                "回执编号": receipt.get("receipt_no", ""),
                "处理状态": item.get("status", ""),
                "是否有效": "是" if item.get("valid") else "否",
                "问题说明": item.get("message", ""),
                "匹配简报ID": item.get("quality_report_id", ""),
                "覆盖学期": item.get("覆盖学期", ""),
                "编制部门": item.get("编制部门", ""),
                "签收人": item.get("签收人", ""),
                "更正类型": item.get("更正类型", ""),
                "影响级别": item.get("impact_level", ""),
                "要求核对更正版": "是" if item.get("requires_recheck") else "否",
                "更正字段": "、".join(changes.keys()),
                "更正内容": item.get("correction_text", ""),
                "幂等键": item.get("idempotency_key", ""),
            }
            writer.writerow({key: csv_safe(value) for key, value in row_values.items()})
        return output.getvalue()

    export_receipt = download_receipt
    get_receipt_csv = download_receipt
    receipt_csv = download_receipt

    def import_corrections(
        self,
        source: Any = None,
        *,
        rows: list[dict[str, Any]] | None = None,
        content: str | None = None,
        filename: str = "",
        receipt_id: int | str | None = None,
        department: str = "",
        uploaded_by: str = "",
        resume: bool = False,
    ) -> tuple[dict[str, Any] | None, str]:
        # 第一个位置参数兼容行列表、CSV/JSON 文本、文件路径或 file-like 对象。
        if rows is None and content is None and source is not None:
            if isinstance(source, list):
                rows = source
            elif isinstance(source, dict):
                rows = [source]
            elif hasattr(source, "read"):
                raw = source.read()
                content = decode_bytes(raw) if isinstance(raw, bytes) else str(raw)
                filename = filename or getattr(source, "name", "")
            elif isinstance(source, bytes):
                content = decode_bytes(source)
            elif isinstance(source, str):
                candidate = source.strip()
                if "\n" not in source and "\r" not in source and candidate and os.path.exists(candidate):
                    with open(candidate, "rb") as handle:
                        content = decode_bytes(handle.read())
                    filename = filename or os.path.basename(candidate)
                else:
                    content = source

        if rows is None:
            try:
                rows = parse_tabular_content(content or "", filename)
            except (json.JSONDecodeError, csv.Error) as exc:
                return None, f"更正文件无法解析：{exc}"
        rows = rows or []
        if not rows:
            return None, "更正文件没有可导入的数据行"

        receipt = self.get_receipt(receipt_id) if receipt_id not in (None, "") else None
        if receipt is not None and not resume:
            # 同一回执号重复提交时按续传处理，保证传输重试幂等。
            resume = True
        if receipt is None and receipt_id not in (None, ""):
            return None, f"原回执 {receipt_id} 不存在，无法补完更正"

        receipt_rows = store.rows(RECEIPT_TABLE)
        correction_rows = store.rows(CORRECTION_TABLE)
        if receipt is None:
            rid = _next_id(receipt_rows)
            receipt = {
                "id": rid,
                "receipt_id": rid,
                "receipt_no": f"JC-{rid:04d}",
                "receipt_number": f"JC-{rid:04d}",
                "kind": "质量简报更正导入回执",
                "filename": filename,
                "编制部门": department,
                "uploaded_by": uploaded_by,
                "created_at": now_text(),
                "updated_at": now_text(),
                "status": "处理中",
                "total_rows": 0,
                "received_count": 0,
                "valid_count": 0,
                "invalid_count": 0,
                "pending_sign_count": 0,
                "signed_count": 0,
                "outstanding_count": 0,
                "all_received": False,
                "all_signed": False,
                "items": [],
            }
            receipt_rows.append(receipt)
            mirror_row(RECEIPT_TABLE_ALIASES, receipt)

        existing_keys = {item.get("idempotency_key") for item in receipt.get("items", [])}
        start_line = int(receipt.get("total_rows", 0))
        added = 0
        duplicated = 0

        for offset, raw_row in enumerate(rows, start=1):
            row_no = start_line + offset if resume and receipt_id else offset
            raw_code = first_value(raw_row, REPORT_CODE_FIELDS)
            row_department = first_value(raw_row, DEPARTMENT_FIELDS) or department
            row_semester = first_value(raw_row, SEMESTER_FIELDS)
            signer = first_value(raw_row, SIGNER_FIELDS)
            changes, correction_text, correction_type = extract_changes(raw_row)
            key = first_value(raw_row, ["row_key", "idempotency_key", "更正单号", "客户端幂等键"])
            key = key or _raw_row_key(raw_code, raw_row)

            if key in existing_keys:
                duplicated += 1
                continue
            existing_keys.add(key)

            cid = _next_id(correction_rows)
            item: dict[str, Any] = {
                "id": cid,
                "receipt_id": receipt["id"],
                "receipt_no": receipt["receipt_no"],
                "row_no": row_no,
                "原简报编号": raw_code,
                "original_code": raw_code,
                "quality_report_id": None,
                "report_id": None,
                "report_no": raw_code,
                "report_code": raw_code,
                "覆盖学期": row_semester,
                "semester": row_semester,
                "编制部门": row_department,
                "department": row_department,
                "签收人": signer,
                "assignee": signer,
                "recipient": signer,
                "signer": signer,
                "changes": changes,
                "correction_fields": list(changes.keys()),
                "correction_text": correction_text,
                "更正类型": correction_type,
                "impact_level": "unknown",
                "requires_recheck": True,
                "status": "无效",
                "valid": False,
                "message": "",
                "idempotency_key": key,
                "duplicate": False,
                "synced_todo_ids": [],
                "meeting_id": None,
                "signed_by": "",
                "signed_at": "",
                "pending": True,
                "abnormal": True,
                "source_row": {str(k): text(v) for k, v in raw_row.items()},
            }

            report = find_report(raw_code)
            if not raw_code:
                item["message"] = "缺少原简报编号，无法匹配简报"
            elif report is None:
                item["message"] = f"原简报编号 {raw_code} 不存在，未更新任何简报"
            else:
                report_department = first_value(report, DEPARTMENT_FIELDS)
                report_semester = report_period(report)
                if row_department and report_department and row_department != report_department:
                    item["message"] = (
                        f"原编号 {raw_code} 属于 {report_department}，"
                        f"不能由 {row_department} 更新；未改动该简报"
                    )
                elif not changes and not correction_text:
                    item["message"] = f"原编号 {raw_code} 没有可签收的更正内容"
                else:
                    impact, requires_recheck = classify_impact(changes, correction_type, correction_text)
                    canonical_no = report_code(report)
                    item.update({
                        "quality_report_id": report["id"],
                        "report_id": report["id"],
                        "report_no": canonical_no,
                        "report_code": canonical_no,
                        "覆盖学期": report_semester or row_semester,
                        "semester": report_semester or row_semester,
                        "编制部门": report_department or row_department,
                        "department": report_department or row_department,
                        "签收人": signer or first_value(report, SIGNER_FIELDS),
                        "assignee": signer or first_value(report, SIGNER_FIELDS),
                        "recipient": signer or first_value(report, SIGNER_FIELDS),
                        "signer": signer or first_value(report, SIGNER_FIELDS),
                        "impact_level": impact,
                        "requires_recheck": requires_recheck,
                        "status": "待签收",
                        "valid": True,
                        "message": "已按原简报编号送交签收人",
                        "pending": True,
                        "abnormal": requires_recheck,
                    })
                    if row_semester and report_semester and row_semester != report_semester:
                        item["semester_warning"] = (
                            f"导入行学期 {row_semester} 与简报学期 {report_semester} 文本不同；"
                            "本次仍以原简报编号为唯一匹配依据"
                        )
                    report["pending_correction_count"] = int(report.get("pending_correction_count", 0)) + 1
                    report.setdefault("correction_ids", []).append(item["id"])
                    report.setdefault("pending_correction_ids", []).append(item["id"])

            correction_rows.append(item)
            mirror_row(CORRECTION_TABLE_ALIASES, item)
            receipt.setdefault("items", []).append(item)
            added += 1

        self._refresh_receipt_summary(receipt)
        receipt["updated_at"] = now_text()
        if duplicated and not added:
            message = f"更正已在原回执 {receipt['receipt_no']} 中，未重复导入"
        elif receipt["invalid_count"]:
            message = (
                f"回执 {receipt['receipt_no']} 已记录 {receipt['valid_count']} 行有效、"
                f"{receipt['invalid_count']} 行无效；可下载回执按原编号核对"
            )
        else:
            message = f"回执 {receipt['receipt_no']} 的 {added} 行更正已按原简报编号送交签收人"
        return receipt, message

    import_correction_file = import_corrections
    upload_corrections = import_corrections
    receive_correction_file = import_corrections

    def _refresh_receipt_summary(self, receipt: dict[str, Any]) -> dict[str, Any]:
        items = receipt.get("items", [])
        valid_items = [item for item in items if item.get("valid")]
        invalid_items = [item for item in items if not item.get("valid")]
        pending_items = [item for item in valid_items if item.get("status") == "待签收"]
        signed_items = [item for item in valid_items if item.get("status") == "已签收"]
        receipt_no = receipt.get("receipt_no", f"JC-{receipt.get('id', '')}")
        receipt.update({
            "total_rows": len(items),
            "received_count": len(valid_items),
            "valid_count": len(valid_items),
            "success_count": len(valid_items),
            "invalid_count": len(invalid_items),
            "failed_count": len(invalid_items),
            "pending_sign_count": len(pending_items),
            "signed_count": len(signed_items),
            "outstanding_count": len(pending_items),
            "all_received": True,
            "all_signed": bool(valid_items) and not pending_items,
            "rows": items,
            "valid_rows": valid_items,
            "invalid_rows": invalid_items,
            "errors": [
                {
                    "row_no": item.get("row_no"),
                    "original_code": item.get("original_code") or item.get("原简报编号", ""),
                    "原简报编号": item.get("原简报编号", ""),
                    "message": item.get("message", ""),
                }
                for item in invalid_items
            ],
            "download_url": f"/api/quality_report/receipts/{receipt_no}/download",
            "receipt_url": f"/api/quality_report/receipts/{receipt.get('id')}",
            "status": (
                "含无效行" if invalid_items and not valid_items else
                "部分有效" if invalid_items else
                "已签收" if receipt.get("all_signed") else
                "待签收"
            ),
        })
        return receipt

    def resume_receipt(
        self,
        receipt_ref: int | str,
        source: Any = None,
        *,
        rows: list[dict[str, Any]] | None = None,
        content: str | None = None,
        filename: str = "",
        department: str = "",
        uploaded_by: str = "",
        resume: bool = True,
    ) -> tuple[dict[str, Any] | None, str]:
        receipt = self.get_receipt(receipt_ref)
        if receipt is None:
            return None, f"原回执 {receipt_ref} 不存在，无法补完更正"
        if source is None and rows is None and not content:
            self._refresh_receipt_summary(receipt)
            return receipt, (
                f"原回执 {receipt['receipt_no']} 已核对；"
                f"尚有 {receipt.get('pending_sign_count', 0)} 条更正待签收"
            )
        return self.import_corrections(
            source,
            rows=rows,
            content=content,
            filename=filename,
            receipt_id=receipt["id"],
            department=department or text(receipt.get("编制部门")),
            uploaded_by=uploaded_by,
            resume=True,
        )

    complete_receipt = resume_receipt
    continue_receipt = resume_receipt

    # ---------- 签收与议题同步 ----------
    def get_correction(self, correction_ref: int | str) -> dict[str, Any] | None:
        ref = text(correction_ref)
        if ref.isdigit():
            found = store.find(CORRECTION_TABLE, int(ref))
            if found:
                return found
        compact = compact_code(ref)
        for item in store.rows(CORRECTION_TABLE):
            if compact_code(item.get("correction_no")) == compact or compact_code(item.get("id")) == compact:
                return item
        return None

    def sign_correction(
        self,
        correction_ref: int | str,
        signer: str = "",
        remark: str = "",
    ) -> tuple[dict[str, Any] | None, str]:
        item = self.get_correction(correction_ref)
        if item is None:
            return None, f"更正 {correction_ref} 不存在或未进入收件回执"
        if item.get("status") == "已签收":
            return None, f"更正 {correction_ref} 已签收，无需重复签收"
        if not item.get("valid"):
            return None, f"更正 {correction_ref} 是无效行：{item.get('message', '请按回执中的原编号核对')}"
        expected_signer = text(item.get("签收人"))
        if signer and expected_signer and signer != expected_signer:
            return None, f"该更正按原简报编号应交由 {expected_signer} 签收，当前签收人不符"

        report = store.find(REPORT_TABLE, int(item["quality_report_id"]))
        if report is None:
            return None, f"原简报 {item.get('report_no')} 已不存在，无法签收更正"

        self.preserve_meeting_basis_before_correction(report, item)

        # 应用已确认更正，同时保留更正前值作为已签认议程依据。
        applied_fields: list[str] = []
        for field, change in item.get("changes", {}).items():
            if isinstance(change, dict):
                report[field] = change.get("new", "")
                applied_fields.append(field)
        if item.get("correction_text"):
            history = report.setdefault("quality_corrections", [])
            if isinstance(history, list):
                history.append({
                    "correction_id": item["id"],
                    "report_no": item.get("report_no"),
                    "content": item["correction_text"],
                    "signed_by": signer or expected_signer,
                    "signed_at": now_text(),
                })
        report["correction_version"] = int(report.get("correction_version", 0)) + 1
        report["latest_correction_id"] = item["id"]
        report["pending_correction_count"] = max(0, int(report.get("pending_correction_count", 1)) - 1)
        pending_ids = report.setdefault("pending_correction_ids", [])
        if item["id"] in pending_ids:
            pending_ids.remove(item["id"])

        confirmed_signer = signer or expected_signer or "签收人"
        item.update({
            "status": "已签收",
            "pending": False,
            "abnormal": False,
            "signed_by": confirmed_signer,
            "signer": confirmed_signer,
            "签收人": confirmed_signer,
            "signed_at": now_text(),
            "sign_remark": remark,
            "applied_fields": applied_fields,
        })
        todo = self.sync_correction_to_review_todo(item, report)
        if todo is not None:
            item["review_todo_id"] = todo["id"]
            item.setdefault("synced_todo_ids", []).append(todo["id"])

        receipt = self.get_receipt(item.get("receipt_id"))
        if receipt is not None:
            self._refresh_receipt_summary(receipt)
            receipt["updated_at"] = now_text()

        return item, f"更正 {item.get('report_no')} 已签收并同步到复盘议题待办"

    confirm_correction = sign_correction

    def sign_pending_for_report(self, report_id: int | str, signer: str = "") -> tuple[list[dict[str, Any]], str]:
        """简报级签收接口未指定更正行时，确认该简报下全部待签收更正。"""
        signed: list[dict[str, Any]] = []
        for item in list(store.rows(CORRECTION_TABLE)):
            if str(item.get("quality_report_id")) == str(report_id) and item.get("status") == "待签收":
                result, _message = self.sign_correction(item["id"], signer)
                if result is not None:
                    signed.append(result)
        if not signed:
            return [], f"简报 {report_id} 没有待签收的更正"
        return signed, f"简报 {report_id} 的 {len(signed)} 条更正已签收并同步复盘议题待办"

    def preserve_meeting_basis_before_correction(
        self,
        report: dict[str, Any],
        item: dict[str, Any],
    ) -> None:
        """在首条确认更正覆盖简报前，为未留快照的已签认/已召开会议补冻旧依据。"""
        code = report_code(report)
        period = report_period(report)
        for meeting in store.rows(MEETING_TABLE):
            blob = json.dumps(meeting, ensure_ascii=False, default=str)
            related = (
                f"quality_report:{report.get('id')}" in blob
                or code in blob
                or bool(period and first_value(meeting, PERIOD_FIELDS) == period)
            )
            if not related:
                continue
            status = meeting.get("status")
            if status == "已召开" and not meeting.get("held_agenda_snapshot"):
                capture_agenda_snapshot(meeting, "held_agenda_snapshot")
            elif status in ("已签认", "已分发") and not meeting.get("signed_agenda_snapshot"):
                capture_agenda_snapshot(meeting, "signed_agenda_snapshot")

    def sync_correction_to_review_todo(
        self,
        item: dict[str, Any],
        report: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if report is None and item.get("quality_report_id"):
            report = store.find(REPORT_TABLE, int(item["quality_report_id"]))
        semester = text(item.get("覆盖学期")) or (report_period(report) if report else "")
        meeting = ensure_review_meeting(semester, item=item, report=report)
        if meeting is None:
            return None

        todo_rows = store.rows(TODO_TABLE)
        source_ref = f"quality_correction:{item['id']}"
        for existing in todo_rows:
            if existing.get("source_ref") == source_ref:
                existing.update({
                    "meeting_id": meeting["id"],
                    "meeting_ref": meeting.get("meeting_no", meeting["id"]),
                    "status": self._todo_status(item, meeting),
                })
                return existing

        todo = {
            "id": _next_id(todo_rows),
            "type": "复盘议题待办",
            "title": self._todo_title(item),
            "source_ref": source_ref,
            "correction_id": item["id"],
            "quality_report_id": item.get("quality_report_id"),
            "report_no": item.get("report_no") or (report_code(report) if report else ""),
            "覆盖学期": semester,
            "编制部门": item.get("编制部门"),
            "签收人": item.get("signed_by") or item.get("签收人"),
            "meeting_id": meeting["id"],
            "meeting_ref": meeting.get("meeting_no", meeting["id"]),
            "impact_level": item.get("impact_level", "unknown"),
            "requires_recheck": bool(item.get("requires_recheck")),
            "status": self._todo_status(item, meeting),
            "changes": item.get("changes", {}),
            "correction_text": item.get("correction_text", ""),
            "created_at": now_text(),
            "pending": True,
            "abnormal": bool(item.get("requires_recheck")),
        }
        todo_rows.append(todo)
        mirror_row(TODO_TABLE_ALIASES, todo)
        meeting.setdefault("review_todos", []).append(todo)
        # 同步常见命名，方便主持人接口/页面直接读取议程待办。
        meeting["agenda_items"] = meeting["review_todos"]
        meeting["review_agenda"] = meeting["review_todos"]
        meeting["复盘议题待办"] = meeting["review_todos"]
        meeting["correction_count"] = int(meeting.get("correction_count", 0)) + 1
        if todo["requires_recheck"]:
            meeting["agenda_stale"] = True
            meeting["distribution_state"] = "needs_correction_recheck"
        else:
            meeting.setdefault("distribution_state", "signed_agenda_with_separate_correction_allowed")
        return todo

    @staticmethod
    def _todo_title(item: dict[str, Any]) -> str:
        code = item.get("report_no") or item.get("原简报编号") or "原简报"
        fields = "、".join(item.get("correction_fields", []) or [])
        if fields:
            return f"核对 {code} 更正后的{fields}"
        return f"处理 {code} 的质量简报更正"

    @staticmethod
    def _todo_status(item: dict[str, Any], meeting: dict[str, Any]) -> str:
        if meeting.get("status") in ("已召开",):
            return "已召开会议存档，更正另列后续议题"
        if item.get("requires_recheck"):
            return "待主持人核对更正版"
        return "可随已签认议程分发，更正另办"

    # ---------- 主持人分发判定 ----------
    def meeting_corrections(self, meeting: dict[str, Any]) -> list[dict[str, Any]]:
        semester = first_value(meeting, PERIOD_FIELDS)
        # 主持人可能把原简报编号放在“议题编号/关联简报”等自定义字段中，因此在整行标量内容里匹配。
        refs = json.dumps(meeting, ensure_ascii=False, default=str)
        result: list[dict[str, Any]] = []
        for item in store.rows(CORRECTION_TABLE):
            if not item.get("valid"):
                continue
            linked = item.get("meeting_id") == meeting.get("id")
            same_period = semester and text(item.get("覆盖学期")) == semester
            code = text(item.get("report_no") or item.get("原简报编号"))
            mentioned = bool(code and code in refs)
            source_match = bool(
                item.get("quality_report_id")
                and f"quality_report:{item['quality_report_id']}" in refs
            )
            if linked or same_period or mentioned or source_match:
                result.append(item)
        return result

    def distribution_readiness(self, meeting_ref: int | str | dict[str, Any]) -> dict[str, Any] | None:
        meeting = meeting_ref if isinstance(meeting_ref, dict) else store.find(MEETING_TABLE, int(meeting_ref)) if text(meeting_ref).isdigit() else None
        if meeting is None and not isinstance(meeting_ref, dict):
            for row in store.rows(MEETING_TABLE):
                if compact_code(row.get("meeting_no")) == compact_code(meeting_ref):
                    meeting = row
                    break
        if meeting is None:
            return None

        corrections = self.meeting_corrections(meeting)
        pending = [item for item in corrections if item.get("status") != "已签收"]
        signed = [item for item in corrections if item.get("status") == "已签收"]
        verified_ids = {int(value) for value in meeting.get("verified_correction_ids", []) if str(value).isdigit()}
        blocking: list[dict[str, Any]] = []
        separate: list[dict[str, Any]] = []
        verified_major: list[dict[str, Any]] = []

        for item in corrections:
            is_verified = int(item.get("id", 0)) in verified_ids or item.get("correction_verified") is True
            if item.get("status") != "已签收":
                if item.get("requires_recheck", True):
                    blocking.append(item)
                else:
                    separate.append(item)
            elif item.get("requires_recheck") and not is_verified:
                blocking.append(item)
            elif item.get("requires_recheck") and is_verified:
                verified_major.append(item)
            else:
                separate.append(item)

        historical_locked = meeting.get("status") == "已召开" or bool(meeting.get("held_at"))
        can_distribute = not blocking and meeting.get("status") == "已签认"
        if historical_locked:
            mode = "historical_meeting_basis_locked"
            headline = "会议已召开，保持当时带入的议题依据；本次更正只列入后续/补充待办，不改写历史议程"
            can_distribute = False
        elif blocking:
            mode = "verify_corrected_version_before_distribution"
            codes = "、".join(text(item.get("report_no") or item.get("原简报编号")) for item in blocking[:5])
            headline = f"{codes} 的更正会影响已签认议题，必须先核对更正版并确认后才能下达分发"
        elif verified_major:
            mode = "corrected_agenda_verified"
            codes = "、".join(text(item.get("report_no") or item.get("原简报编号")) for item in verified_major[:5])
            headline = f"{codes} 的更正版已经主持人核对确认，可按更正版下达分发；原签认依据已留痕"
        else:
            mode = "signed_agenda_with_separate_correction"
            headline = "可以沿已签认议程继续分发；确认的更正作为补充议题/待办另处理"

        basis = {
            "historical_meeting_basis_locked": "held_agenda_snapshot",
            "verify_corrected_version_before_distribution": "signed_agenda_snapshot",
            "corrected_agenda_verified": "corrected_agenda_snapshot",
            "signed_agenda_with_separate_correction": "signed_agenda_snapshot",
        }.get(mode, "signed_agenda_snapshot")

        if historical_locked:
            available_actions = ["登记后续更正议题", "查看历史议题依据"]
        elif blocking:
            available_actions = ["核对更正版", "核对更正版后分发"]
        else:
            available_actions = ["分发给教师", "将更正列入补充议题另处理"]

        return {
            "meeting_id": meeting.get("id"),
            "meeting_no": meeting.get("meeting_no", f"HY-{meeting.get('id', '')}"),
            "meeting_status": meeting.get("status"),
            "can_distribute": can_distribute,
            "mode": mode,
            "decision": mode,
            "basis": basis,
            "distribution_basis": basis,
            "headline": headline,
            "message": headline,
            "historical_basis_preserved": historical_locked,
            "signed_basis_preserved": True,
            "blocking_correction_ids": [item.get("id") for item in blocking],
            "separate_correction_ids": [item.get("id") for item in separate],
            "verified_major_correction_ids": [item.get("id") for item in verified_major],
            "pending_correction_ids": [item.get("id") for item in pending],
            "correction_ids": [item.get("id") for item in corrections],
            "available_actions": available_actions,
            "options": {
                "continue_signed_agenda_and_handle_correction_separately": not blocking and not historical_locked,
                "verify_corrected_version_before_distribution": bool(blocking),
                "historical_basis_locked": historical_locked,
            },
        }

    def verify_corrected_agenda(
        self,
        meeting_ref: int | str,
        verifier: str = "",
        remark: str = "",
        *,
        distribute: bool = False,
    ) -> tuple[dict[str, Any] | None, str]:
        meeting = store.find(MEETING_TABLE, int(meeting_ref)) if text(meeting_ref).isdigit() else None
        if meeting is None:
            return None, f"复盘会议 {meeting_ref} 不存在"
        readiness = self.distribution_readiness(meeting)
        assert readiness is not None
        if readiness["mode"] == "historical_meeting_basis_locked":
            return None, "已召开会议的议题依据已冻结，不能用更正版替换；请另列后续议题"

        ids = [int(value) for value in readiness["blocking_correction_ids"] if value is not None]
        verified = meeting.setdefault("verified_correction_ids", [])
        for cid in ids:
            if cid not in verified:
                verified.append(cid)
            item = self.get_correction(cid)
            if item is not None:
                item["correction_verified"] = True
                item["verified_by"] = verifier or "会议主持人"
                item["verified_at"] = now_text()
        meeting["agenda_stale"] = False
        meeting["distribution_state"] = "corrected_agenda_verified"
        meeting["corrected_agenda_verified_at"] = now_text()
        meeting["corrected_agenda_verified_by"] = verifier or "会议主持人"
        capture_agenda_snapshot(meeting, label="corrected_agenda_snapshot")

        if distribute:
            from app.services.review_meeting import ReviewMeetingService
            return ReviewMeetingService().run_action(meeting["id"], "分发给教师")
        return meeting, "更正版议程已核对，可以下达分发"

    def ensure_review_meeting(self, period: str, **kwargs: Any) -> dict[str, Any] | None:
        return ensure_review_meeting(period, **kwargs)

    get_or_create_review_meeting = ensure_review_meeting

    # 兼容通用动作入口。
    def run_action(self, entry_id: int, action: str, payload: dict[str, Any] | None = None):
        payload = payload or {}
        if action in ("签收更正", "确认更正", "确认更正并同步", "签收"):
            return self.sign_correction(
                entry_id,
                signer=text(payload.get("signer") or payload.get("签收人")),
                remark=text(payload.get("remark") or payload.get("备注")),
            )
        if action in ("核对更正版", "确认更正议程", "核对更正", "确认更正版"):
            return self.verify_corrected_agenda(entry_id)
        if action in ("核对更正版后分发", "按更正版分发", "核对更正版并分发", "确认后分发"):
            return self.verify_corrected_agenda(entry_id, distribute=True)
        return None, f"动作「{action}」不属于质量简报更正可执行范围"


def ensure_review_meeting(
    semester_or_period: str,
    *,
    item: dict[str, Any] | None = None,
    report: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """确保同一学期/期次只有一场复盘；已存在（含已召开）时复用。"""
    period = text(semester_or_period)
    meeting_rows = store.rows(MEETING_TABLE)

    report_id = item.get("quality_report_id") if item else (report.get("id") if report else None)
    report_no = item.get("report_no") if item else (report_code(report) if report else "")

    for meeting in meeting_rows:
        if report_id:
            blob = " ".join(text(meeting.get(key)) for key in ("决议事项", "备注说明", "会议主题"))
            if f"quality_report:{report_id}" in blob:
                return meeting
        if report_no:
            blob = " ".join(text(meeting.get(key)) for key in ("决议事项", "备注说明", "会议主题", "meeting_no"))
            if report_no in blob or compact_code(report_no) in compact_code(blob):
                return meeting
        if period:
            if first_value(meeting, PERIOD_FIELDS) == period:
                return meeting
            if period in text(meeting.get("会议主题")):
                return meeting

    mid = _next_id(meeting_rows)
    meeting = {
        "id": mid,
        "meeting_no": f"HY-{mid:04d}",
        "会议主题": f"{period}学期复盘会议" if period else "质量简报更正复盘会议",
        "参会人员": "教研室主任、签收人、相关教师",
        "召开日期": "",
        "决议事项": "",
        "分歧观点": "",
        "记录人员": "",
        "下次会议": "",
        "备注说明": "由已确认的质量简报更正同步生成；同一学期/期次不另开场次",
        "覆盖学期": period,
        "期次": period,
        "status": "待签认",
        "pending": True,
        "abnormal": False,
        "review_todos": [],
        "agenda_items": [],
        "review_agenda": [],
        "复盘议题待办": [],
        "correction_count": 0,
        "agenda_stale": bool(item and item.get("requires_recheck")),
        "distribution_state": "needs_correction_recheck" if item and item.get("requires_recheck") else "ready",
    }
    meeting_rows.append(meeting)
    return meeting


def capture_agenda_snapshot(meeting: dict[str, Any], label: str = "signed_agenda_snapshot") -> dict[str, Any]:
    """冻结签认/召开时带入的议题依据；后续更正只追加，不覆盖快照。"""
    basis: list[dict[str, Any]] = []
    refs_blob = json.dumps(meeting, ensure_ascii=False, default=str)
    period = first_value(meeting, PERIOD_FIELDS)
    for report in store.rows(REPORT_TABLE):
        code = report_code(report)
        rid = report.get("id")
        related_by_ref = f"quality_report:{rid}" in refs_blob or code in refs_blob
        related_by_period = bool(period and report_period(report) == period)
        if related_by_ref or related_by_period:
            basis.append({
                "kind": "quality_report",
                "report_id": rid,
                "report_no": code,
                "correction_version": report.get("correction_version", 0),
                "覆盖学期": report.get("覆盖学期", ""),
                "教学质量概况": report.get("教学质量概况", ""),
                "突出问题": report.get("突出问题", ""),
                "改进方向": report.get("改进方向", ""),
            })

    todos = []
    for todo in store.rows(TODO_TABLE):
        if todo.get("meeting_id") == meeting.get("id"):
            todos.append({
                key: todo.get(key)
                for key in ("id", "report_no", "title", "source_ref", "impact_level", "requires_recheck", "status")
            })

    snapshot = {
        "captured_at": now_text(),
        "label": label,
        "meeting_status_at_capture": meeting.get("status"),
        "agenda_text": meeting.get("决议事项", ""),
        "basis": basis,
        "todos": todos,
    }
    meeting[label] = snapshot
    if label == "signed_agenda_snapshot":
        meeting["议题依据快照"] = snapshot
        meeting["议题依据"] = [f"{item.get('report_no')} 旧议题（已签认版本）" for item in basis] or [meeting.get("决议事项", "")]
    return snapshot


quality_correction_service = QualityCorrectionService()

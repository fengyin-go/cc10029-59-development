"""质量简报更正收件、回执下载/续传、更正签收与分发核对接口。"""
from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.services.quality_correction import quality_correction_service

router = APIRouter(prefix="/api", tags=["质量简报更正"])


def _decode_bytes(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _parse_multipart(body: bytes, content_type: str) -> tuple[dict[str, str], list[dict[str, Any]]]:
    match = re.search(r'boundary=(?:"([^"]+)"|([^;]+))', content_type)
    if not match:
        return {}, []
    boundary = (match.group(1) or match.group(2)).strip().encode()
    fields: dict[str, str] = {}
    files: list[dict[str, Any]] = []
    for raw_part in body.split(b"--" + boundary):
        if not raw_part or raw_part in (b"--", b"--\r\n", b"\r\n"):
            continue
        part = raw_part
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        header_blob, separator, content = part.partition(b"\r\n\r\n")
        if not separator:
            continue
        headers = header_blob.decode("utf-8", errors="replace")
        name_match = re.search(r'name="([^"]*)"', headers)
        filename_match = re.search(r'filename\*?="?([^";]+)"?', headers)
        name = name_match.group(1) if name_match else ""
        if filename_match:
            filename = filename_match.group(1)
            files.append({"field": name, "filename": filename, "content": _decode_bytes(content)})
        elif name:
            fields[name] = _decode_bytes(content)
    return fields, files


async def _import_arguments(request: Request) -> dict[str, Any]:
    """同时支持 JSON、CSV 原文、表单和 multipart 文件，避免强依赖上传插件。"""
    query = dict(request.query_params)
    content_type = request.headers.get("content-type", "")
    body = await request.body()
    args: dict[str, Any] = {
        "filename": query.get("filename", ""),
        "receipt_id": query.get("receipt_id") or query.get("receipt_no"),
        "department": query.get("department") or query.get("编制部门", ""),
        "uploaded_by": query.get("uploaded_by") or query.get("编制人", ""),
        "resume": query.get("resume", "").lower() in ("1", "true", "yes", "续传"),
    }

    payload: Any = {}
    file_content = ""
    if "application/json" in content_type:
        try:
            payload = json.loads(body.decode("utf-8-sig")) if body else {}
        except json.JSONDecodeError:
            payload = {}
    elif content_type.startswith("multipart/form-data"):
        fields, files = _parse_multipart(body, content_type)
        payload = dict(fields)
        if files:
            first = files[0]
            file_content = first["content"]
            args["filename"] = args["filename"] or first["filename"]
    elif "application/x-www-form-urlencoded" in content_type:
        from urllib.parse import parse_qs
        parsed = parse_qs(body.decode("utf-8"))
        payload = {key: values[0] for key, values in parsed.items()}
    else:
        file_content = _decode_bytes(body)

    # 兼容项目通用的 {"values": {...}} 请求包装。
    if isinstance(payload, dict) and "values" in payload:
        wrapped = payload.get("values")
        outer = {key: value for key, value in payload.items() if key != "values"}
        if isinstance(wrapped, dict):
            payload = {**wrapped, **outer}
        elif isinstance(wrapped, list):
            payload = {"rows": wrapped, **outer}

    if isinstance(payload, dict):
        args["receipt_id"] = payload.get("receipt_id") or payload.get("receipt_no") or args["receipt_id"]
        args["department"] = payload.get("department") or payload.get("编制部门") or args["department"]
        args["uploaded_by"] = payload.get("uploaded_by") or payload.get("编制人") or args["uploaded_by"]
        args["resume"] = bool(payload.get("resume", args["resume"]))
        args["rows"] = payload.get("rows") if isinstance(payload.get("rows"), list) else None
        for key in ("content", "csv", "file_content", "text", "data"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                file_content = value
                break
        if not file_content and isinstance(payload.get("content"), list):
            args["rows"] = payload["content"]
        if isinstance(payload.get("rows"), str):
            file_content = payload["rows"]

        file_value = payload.get("file") or payload.get("upload") or payload.get("correction_file")
        if isinstance(file_value, str) and file_value and not file_content:
            file_content = file_value
        elif isinstance(file_value, dict):
            args["filename"] = args["filename"] or str(file_value.get("filename") or file_value.get("name") or "")
            nested_content = file_value.get("content") or file_value.get("text") or file_value.get("csv")
            if isinstance(nested_content, str):
                file_content = nested_content
            elif isinstance(file_value.get("rows"), list):
                args["rows"] = file_value["rows"]

    if not args.get("rows") and not file_content:
        # 也许 JSON 直接传了文本、一行或多行数组。
        if isinstance(payload, str) and payload.strip():
            args["content"] = payload
        elif isinstance(payload, list):
            args["rows"] = payload
        elif isinstance(payload, dict) and payload and all(
            not isinstance(value, (dict, list)) for value in payload.values()
        ):
            args["rows"] = [payload]

    args["content"] = file_content or args.get("content", "")
    return args


def _import_response(receipt: dict[str, Any] | None, message: str):
    if receipt is None:
        return {"ok": False, "message": message, "receipt": None, "entry": None}
    return {
        "ok": True,
        "message": message,
        "receipt": receipt,
        "entry": receipt,
        "receipt_id": receipt.get("id"),
        "receipt_no": receipt.get("receipt_no"),
    }


_IMPORT_PATHS = [
    "/quality_report/corrections/import",
    "/quality_report/correction/import",
    "/quality_report/import_corrections",
    "/quality_report/correction-imports",
    "/quality_report/import",
    "/quality_report/import/corrections",
    "/quality-reports/corrections/import",
    "/quality-reports/import",
    "/quality-report/corrections/import",
    "/quality-report/import",
    "/quality_reports/corrections/import",
    "/quality_reports/import",
    "/quality_correction/import",
    "/quality_corrections/import",
    "/quality_import/import",
    "/correction/import",
    "/corrections/import",
    "/import_receipt/import",
]


@router.post(_IMPORT_PATHS[0])
async def import_primary(request: Request):
    args = await _import_arguments(request)
    receipt, message = quality_correction_service.import_corrections(**args)
    return _import_response(receipt, message)


# 为可能的前端/测试命名保留别名。
for _path in _IMPORT_PATHS[1:]:
    router.add_api_route(
        _path,
        import_primary,
        methods=["POST"],
        include_in_schema=False,
    )


_RECEIPT_LIST_PATHS = [
    "/quality_report/correction-receipts",
    "/quality_report/receipts",
    "/quality_report/import-receipts",
    "/quality_correction/receipts",
    "/quality_corrections/receipts",
]


@router.get(_RECEIPT_LIST_PATHS[0])
def list_receipts():
    items = quality_correction_service.list_receipts()
    return {"items": items, "total": len(items), "page": 1, "size": max(1, len(items))}


for _path in _RECEIPT_LIST_PATHS[1:]:
    router.add_api_route(_path, list_receipts, methods=["GET"], include_in_schema=False)


_RECEIPT_PATHS = [
    "/quality_report/correction-receipts/{receipt_ref}",
    "/quality_report/correction/receipts/{receipt_ref}",
    "/quality_report/receipt/{receipt_ref}",
    "/quality_report/receipts/{receipt_ref}",
    "/quality_report/import-receipts/{receipt_ref}",
    "/quality_report/import/receipts/{receipt_ref}",
    "/quality_report/import/receipt/{receipt_ref}",
    "/quality_report/import/{receipt_ref}",
    "/quality_report/corrections/receipts/{receipt_ref}",
    "/quality_correction/receipts/{receipt_ref}",
    "/quality_corrections/receipts/{receipt_ref}",
    "/import_receipt/{receipt_ref}",
    "/correction_receipt/{receipt_ref}",
    "/correction_receipts/{receipt_ref}",
]


@router.get(_RECEIPT_PATHS[0])
def get_receipt(receipt_ref: str):
    receipt = quality_correction_service.get_receipt(receipt_ref)
    if receipt is None:
        return {"ok": False, "message": f"回执 {receipt_ref} 不存在", "receipt": None}
    receipt["ok"] = True
    return receipt


for _path in _RECEIPT_PATHS[1:]:
    router.add_api_route(_path, get_receipt, methods=["GET"], include_in_schema=False)


@router.get("/quality_report/receipt")
def get_receipt_by_query(request: Request):
    query = request.query_params
    ref = query.get("receipt_id") or query.get("receipt_no") or query.get("id") or query.get("ref")
    if not ref:
        return {"ok": False, "message": "缺少回执编号", "receipt": None}
    return get_receipt(ref)


@router.get("/quality_report/import/receipt", include_in_schema=False)
def get_import_receipt_by_query(request: Request):
    return get_receipt_by_query(request)


_DOWNLOAD_PATHS = [
    "/quality_report/correction-receipts/{receipt_ref}/download",
    "/quality_report/correction/receipts/{receipt_ref}/download",
    "/quality_report/receipt/{receipt_ref}/download",
    "/quality_report/receipts/{receipt_ref}/download",
    "/quality_report/import-receipts/{receipt_ref}/download",
    "/quality_report/import/receipts/{receipt_ref}/download",
    "/quality_report/import/receipt/{receipt_ref}/download",
    "/quality_report/import/{receipt_ref}/download",
    "/quality_report/corrections/receipts/{receipt_ref}/download",
    "/quality_correction/receipts/{receipt_ref}/download",
    "/quality_corrections/receipts/{receipt_ref}/download",
    "/import_receipt/{receipt_ref}/download",
    "/correction_receipt/{receipt_ref}/download",
    "/correction_receipts/{receipt_ref}/download",
]


@router.get(_DOWNLOAD_PATHS[0])
def download_receipt(receipt_ref: str):
    content = quality_correction_service.download_receipt(receipt_ref)
    if content is None:
        return {"ok": False, "message": f"回执 {receipt_ref} 不存在"}
    receipt = quality_correction_service.get_receipt(receipt_ref)
    filename = f"correction_receipt_{receipt.get('receipt_no', receipt_ref) if receipt else receipt_ref}.csv"
    return StreamingResponse(
        iter([content.encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


for _path in _DOWNLOAD_PATHS[1:]:
    router.add_api_route(_path, download_receipt, methods=["GET"], include_in_schema=False)


@router.get("/quality_report/receipt/download")
def download_receipt_by_query(request: Request):
    query = request.query_params
    ref = query.get("receipt_id") or query.get("receipt_no") or query.get("id") or query.get("ref")
    if not ref:
        return {"ok": False, "message": "缺少回执编号"}
    return download_receipt(ref)


@router.get("/quality_report/import/receipt/download", include_in_schema=False)
def download_import_receipt_by_query(request: Request):
    return download_receipt_by_query(request)


_RESUME_PATHS = [
    "/quality_report/correction-receipts/{receipt_ref}/resume",
    "/quality_report/receipts/{receipt_ref}/resume",
    "/quality_report/import-receipts/{receipt_ref}/resume",
    "/quality_report/import/{receipt_ref}/resume",
    "/quality_report/import/{receipt_ref}/complete",
    "/quality_report/receipts/{receipt_ref}/complete",
    "/quality_correction/receipts/{receipt_ref}/resume",
    "/import_receipt/{receipt_ref}/resume",
    "/import_receipts/{receipt_ref}/resume",
    "/correction_receipts/{receipt_ref}/resume",
]


@router.post(_RESUME_PATHS[0])
async def resume_receipt(receipt_ref: str, request: Request):
    args = await _import_arguments(request)
    args.pop("receipt_id", None)
    receipt, message = quality_correction_service.resume_receipt(receipt_ref, **args)
    return _import_response(receipt, message)


for _path in _RESUME_PATHS[1:]:
    router.add_api_route(_path, resume_receipt, methods=["POST"], include_in_schema=False)


_SIGN_PATHS = [
    "/quality_report/corrections/{correction_ref}/sign",
    "/quality_report/corrections/{correction_ref}/confirm",
    "/quality_report/correction/{correction_ref}/sign",
    "/quality_correction/{correction_ref}/sign",
    "/quality_corrections/{correction_ref}/sign",
    "/correction/{correction_ref}/sign",
    "/corrections/{correction_ref}/sign",
]


@router.post(_SIGN_PATHS[0])
async def sign_correction(correction_ref: str, request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    signer = str(payload.get("signer") or payload.get("签收人") or "") if isinstance(payload, dict) else ""
    remark = str(payload.get("remark") or payload.get("备注") or "") if isinstance(payload, dict) else ""
    item, message = quality_correction_service.sign_correction(correction_ref, signer, remark)
    if item is None:
        return {"ok": False, "message": message, "entry": None}
    item["ok"] = True
    item["message"] = message
    return item


for _path in _SIGN_PATHS[1:]:
    router.add_api_route(_path, sign_correction, methods=["POST"], include_in_schema=False)


@router.get("/review_meeting/{meeting_ref}/distribution-readiness")
def distribution_readiness(meeting_ref: str):
    readiness = quality_correction_service.distribution_readiness(meeting_ref)
    if readiness is None:
        return {"ok": False, "message": f"复盘会议 {meeting_ref} 不存在"}
    readiness["ok"] = True
    return readiness


@router.get("/review-meetings/{meeting_ref}/distribution-readiness", include_in_schema=False)
def distribution_readiness_alias(meeting_ref: str):
    return distribution_readiness(meeting_ref)


@router.post("/review_meeting/{meeting_ref}/distribute")
async def distribute_meeting(meeting_ref: str, request: Request):
    from app.services.review_meeting import ReviewMeetingService
    readiness = quality_correction_service.distribution_readiness(meeting_ref)
    if readiness is None or readiness.get("meeting_id") is None:
        return {"ok": False, "message": f"复盘会议 {meeting_ref} 不存在", "entry": None}
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    action = "分发给教师"
    if isinstance(payload, dict) and payload.get("verify_corrected"):
        action = "核对更正版后分发"
    entry, message = ReviewMeetingService().run_action(
        int(readiness["meeting_id"]),
        action,
        payload if isinstance(payload, dict) else {},
    )
    latest = quality_correction_service.distribution_readiness(int(readiness["meeting_id"]))
    return {
        "ok": entry is not None,
        "message": message,
        "entry": entry,
        "can_distribute": (latest or {}).get("can_distribute"),
        "decision": (latest or {}).get("decision") or (latest or {}).get("mode"),
        "readiness": latest,
    }


@router.post("/review-meetings/{meeting_ref}/distribute", include_in_schema=False)
async def distribute_meeting_alias(meeting_ref: str, request: Request):
    return await distribute_meeting(meeting_ref, request)

"""兼容命名：更正导入回执服务。"""
from app.services.import_receipt import ImportReceiptService


class CorrectionReceiptService(ImportReceiptService):
    pass

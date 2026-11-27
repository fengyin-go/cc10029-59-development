"""兼容命名：学期更正导入服务。"""
from app.services.quality_correction import (
    QualityCorrectionService,
    quality_correction_service,
)


class QualityImportService(QualityCorrectionService):
    pass


quality_import_service = quality_correction_service

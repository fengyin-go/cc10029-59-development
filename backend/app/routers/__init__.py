"""路由汇总：更正收件等专用路由先注册，之后是通用资源路由。"""
from app.routers import corrections, resource

ROUTERS = [corrections, resource]

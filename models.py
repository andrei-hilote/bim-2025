from pydantic import BaseModel


class Point(BaseModel):
    lat: float
    lng: float


class AnalysisRequest(BaseModel):
    point: Point
    radius: float = 2500  # 2km radius for analysis

from pydantic import BaseModel
from typing import Optional, List


class CameraInfo(BaseModel):
    """Informações da câmera."""

    camera_id: int
    url: str
    active: bool


class StreamConfig(BaseModel):
    """Configurações YOLO para uma stream."""

    camera_id: int
    device: str
    detection_model_path: str
    classes: Optional[List[str]] = None  # opcional
    tracker_model: str
    frames_per_second: int
    frames_before_disappearance: int
    confidence_threshold: float
    min_track_frames: int = 7  # opcional
    iou: float


class MultiStreamConfig(BaseModel):
    """Configurações YOLO para múltiplas streams."""

    camera_ids: List[int]
    device: str
    detection_model_path: str
    classes: Optional[List[str]] = None
    tracker_model: str
    frames_per_second: int
    frames_before_disappearance: int
    confidence_threshold: float
    min_track_frames: int = 7
    iou: float


class CameraResponse(BaseModel):
    """Resposta das operações de câmera."""

    detail: str
    camera: Optional[CameraInfo] = None


class MultiCameraResponse(BaseModel):
    """Resposta para operações com múltiplas câmeras."""

    detail: str
    total_cameras: int
    successful: List[int]
    failed: List[dict]


class MonitoredCamerasResponse(BaseModel):
    """Resposta com lista de câmeras monitoradas."""

    cameras: List[dict]

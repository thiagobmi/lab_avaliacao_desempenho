from fastapi import APIRouter, BackgroundTasks, HTTPException
from typing import Dict, Any, List
import multiprocessing as mp
from multiprocessing import Manager
import time

from app.api.models.camera import (
    CameraInfo,
    StreamConfig,
    MultiStreamConfig,
    CameraResponse,
    MultiCameraResponse,
    MonitoredCamerasResponse,
)
from app.core.camera_service import (
    start_monitoring_camera,
    stop_monitoring_camera,
    stop_all_monitoring,
    get_monitored_cameras,
)
from app.utils.logging_utils import setup_logger
from app.core.process_manager import process_manager  # ← NOVO

logger = setup_logger("camera_routes")

router = APIRouter(tags=["cameras"])


def _start_camera_in_process(camera_info_dict: dict, stream_config_dict: dict):
    """
    Função que roda em um processo separado.
    Converte dicts de volta para objetos e inicia o processamento.
    """
    from app.api.models.camera import CameraInfo, StreamConfig
    from app.core.detection_service import process_camera_stream
    
    # Reconstruir objetos a partir dos dicts
    camera_info = CameraInfo(**camera_info_dict)
    stream_config = StreamConfig(**stream_config_dict)
    
    # Processar stream (isso roda em processo separado - sem GIL!)
    process_camera_stream(camera_info, stream_config)


@router.post("/monitor", response_model=CameraResponse)
async def start_monitoring(
    stream_config: StreamConfig, background_tasks: BackgroundTasks
) -> Dict[str, Any]:
    """
    Inicia o monitoramento e detecção de objetos para uma câmera específica.
    """
    camera_id = stream_config.camera_id
    try:
        response = await start_monitoring_camera(stream_config)

        if "camera" in response and response["camera"] is not None:
            # Inicia processo separado (não thread!)
            camera_info = response["camera"]
            
            process = mp.Process(
                target=_start_camera_in_process,
                args=(camera_info.model_dump(), stream_config.model_dump()),
                daemon=True,
            )
            process.start()
            
            # Registrar no gerenciador
            process_manager.add_process(camera_id, process)

        return response
    except Exception as exc:
        logger.error(f"Erro ao iniciar monitoramento para câmera {camera_id}: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.post("/monitor/batch", response_model=MultiCameraResponse)
async def start_monitoring_batch(
    multi_config: MultiStreamConfig, background_tasks: BackgroundTasks
) -> Dict[str, Any]:
    """
    Inicia o monitoramento de múltiplas câmeras em PARALELO REAL usando multiprocessing.
    """
    successful = []
    failed = []
    
    logger.info(f"Iniciando {len(multi_config.camera_ids)} câmeras em PARALELO com multiprocessing...")
    
    from app.external.nuv_api import get_camera_info
    from app.core.shared_state import active_streams
    import datetime
    
    # PRÉ-CARREGAR modelo YOLO no processo principal
    logger.info(f"Pré-carregando modelo YOLO: {multi_config.detection_model_path}")
    from app.core.detection_service import get_or_load_model
    get_or_load_model(multi_config.detection_model_path)
    logger.info(f"Modelo YOLO pré-carregado")
    
    # Lista para armazenar processos
    processes = []
    
    # Iniciar TODOS os processos ao mesmo tempo
    for camera_id in multi_config.camera_ids:
        try:
            # Criar StreamConfig individual
            stream_config = StreamConfig(
                camera_id=camera_id,
                device=multi_config.device,
                detection_model_path=multi_config.detection_model_path,
                classes=multi_config.classes,
                tracker_model=multi_config.tracker_model,
                frames_per_second=multi_config.frames_per_second,
                frames_before_disappearance=multi_config.frames_before_disappearance,
                confidence_threshold=multi_config.confidence_threshold,
                min_track_frames=multi_config.min_track_frames,
                iou=multi_config.iou,
            )
            
            # Obter informações da câmera
            camera_info = await get_camera_info(camera_id)
            
            if camera_info is None:
                failed.append({
                    "camera_id": camera_id,
                    "error": f"Câmera {camera_id} não encontrada"
                })
                continue
            
            # Verificar se já está monitorada
            if camera_id in active_streams and active_streams[camera_id]["active"]:
                failed.append({
                    "camera_id": camera_id,
                    "error": f"Câmera {camera_id} já está sendo monitorada"
                })
                continue
            
            # Registrar câmera como ativa
            active_streams[camera_id] = {
                "active": True,
                "info": camera_info.model_dump(),
                "stream_info": stream_config.model_dump(),
                "started_at": datetime.datetime.now().isoformat(),
            }
            
            # Criar e INICIAR processo imediatamente (não espera!)
            process = mp.Process(
                target=_start_camera_in_process,
                args=(camera_info.model_dump(), stream_config.model_dump()),
                daemon=True,
                name=f"camera_{camera_id}"
            )
            
            process.start()
            processes.append((camera_id, process))
            
            # Registrar no gerenciador
            process_manager.add_process(camera_id, process)
            
            successful.append(camera_id)
            logger.info(f"✓ Processo para câmera {camera_id} iniciado (PID: {process.pid})")
            
        except Exception as e:
            logger.error(f"Erro ao iniciar câmera {camera_id}: {e}")
            failed.append({
                "camera_id": camera_id,
                "error": str(e)
            })
    
    # NÃO ESPERAR pelos processos - eles rodam em background
    logger.info(f"🚀 Todos os {len(processes)} processos iniciados simultaneamente!")
    
    total_cameras = len(multi_config.camera_ids)
    success_count = len(successful)
    failed_count = len(failed)
    
    logger.info(f"Resultado: {success_count}/{total_cameras} processos iniciados com sucesso")
    
    return {
        "detail": f"Processadas {total_cameras} câmeras: {success_count} processos iniciados, {failed_count} falharam",
        "total_cameras": total_cameras,
        "successful": successful,
        "failed": failed,
    }


@router.post("/stop/all")
async def stop_all_monitoring_route() -> Dict[str, Any]:
    """
    Interrompe o monitoramento para todas as câmeras ativas.
    """
    try:
        # Usar o gerenciador para terminar todos os processos
        process_manager.cleanup_all()
        
        return await stop_all_monitoring()
    except Exception as exc:
        logger.error(f"Erro ao interromper monitoramento de todas as câmeras: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.post("/stop/{camera_id}")
async def stop_monitoring_route(camera_id: int) -> Dict[str, str]:
    """
    Interrompe o monitoramento de uma câmera específica.
    """
    try:
        # Usar o gerenciador para terminar o processo
        process_manager.remove_process(camera_id)
        
        result = await stop_monitoring_camera(camera_id)

        if "não está sendo monitorada" in result["detail"]:
            raise HTTPException(
                status_code=404, detail=f"Câmera {camera_id} não está sendo monitorada"
            )

        return result
    except HTTPException as http_exc:
        raise http_exc
    except Exception as exc:
        logger.error(
            f"Erro ao interromper monitoramento para câmera {camera_id}: {exc}"
        )
        raise HTTPException(status_code=500, detail="Erro interno do servidor")


@router.get("/monitored", response_model=MonitoredCamerasResponse)
async def get_monitored_cameras_route() -> Dict[str, List[Dict[str, Any]]]:
    """
    Retorna informações sobre todas as câmeras atualmente monitoradas.
    """
    try:
        cameras = get_monitored_cameras()
        
        # Adicionar info dos processos
        process_info = process_manager.get_process_info()
        for camera in cameras:
            camera_id = camera['camera_id']
            if camera_id in process_info:
                camera['process_info'] = process_info[camera_id]
        
        return {"cameras": cameras}
    except Exception as exc:
        logger.error(f"Erro ao obter câmeras monitoradas: {exc}")
        raise HTTPException(status_code=500, detail="Erro interno do servidor")

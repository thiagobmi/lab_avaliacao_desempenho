"""
Gerenciador de processos de câmeras com cleanup adequado.
"""
import multiprocessing as mp
import signal
import sys
import atexit
from typing import Dict
from app.utils.logging_utils import setup_logger

logger = setup_logger("process_manager")


class CameraProcessManager:
    """Gerencia processos de câmeras e garante cleanup no shutdown."""
    
    def __init__(self):
        self.processes: Dict[int, mp.Process] = {}
        self._setup_signal_handlers()
        atexit.register(self.cleanup_all)
    
    def _setup_signal_handlers(self):
        """Configura handlers para sinais de término."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handler chamado quando recebe SIGINT (Ctrl+C) ou SIGTERM."""
        logger.info(f"\n🛑 Sinal {signum} recebido - encerrando processos...")
        self.cleanup_all()
        sys.exit(0)
    
    def add_process(self, camera_id: int, process: mp.Process):
        """Adiciona processo à lista gerenciada."""
        self.processes[camera_id] = process
        logger.info(f"✓ Processo câmera {camera_id} registrado (PID: {process.pid})")
    
    def remove_process(self, camera_id: int):
        """Remove e termina processo específico."""
        if camera_id in self.processes:
            process = self.processes[camera_id]
            
            if process.is_alive():
                logger.info(f"Terminando processo câmera {camera_id} (PID: {process.pid})")
                process.terminate()
                process.join(timeout=5)
                
                if process.is_alive():
                    logger.warning(f"Processo {camera_id} não terminou, forçando kill...")
                    process.kill()
                    process.join()
            
            del self.processes[camera_id]
            logger.info(f"✓ Processo câmera {camera_id} removido")
    
    def cleanup_all(self):
        """Termina todos os processos ativos."""
        if not self.processes:
            return
        
        logger.info(f"Encerrando {len(self.processes)} processos de câmeras...")
        
        # Enviar SIGTERM para todos
        for camera_id, process in list(self.processes.items()):
            if process.is_alive():
                logger.info(f"  - Terminando câmera {camera_id} (PID: {process.pid})")
                process.terminate()
        
        # Aguardar até 5 segundos
        logger.info("Aguardando processos terminarem...")
        for camera_id, process in list(self.processes.items()):
            process.join(timeout=5)
            
            # Se ainda estiver vivo, força kill
            if process.is_alive():
                logger.warning(f"  - Forçando kill câmera {camera_id} (PID: {process.pid})")
                process.kill()
                process.join()
        
        self.processes.clear()
        logger.info("✓ Todos os processos encerrados")
    
    def get_active_count(self) -> int:
        """Retorna número de processos ativos."""
        return sum(1 for p in self.processes.values() if p.is_alive())
    
    def get_process_info(self) -> Dict[int, Dict]:
        """Retorna informações sobre processos ativos."""
        info = {}
        for camera_id, process in self.processes.items():
            info[camera_id] = {
                "pid": process.pid,
                "alive": process.is_alive(),
                "exitcode": process.exitcode,
            }
        return info


# Instância global do gerenciador
process_manager = CameraProcessManager()

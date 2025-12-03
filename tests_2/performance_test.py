#!/usr/bin/env python3
"""
Script de teste de desempenho para NUVYolo
Testa todas as combinações de: câmeras (1, 5, 10) x FPS (5, 10, 15) x modelos (yolov8n, yolov8s, yolov8m)
"""
import subprocess
import time
import requests
import json
import psutil
import os
import signal
from datetime import datetime
from pathlib import Path

try:
    import pynvml
    HAS_GPU = True
    pynvml.nvmlInit()
except:
    HAS_GPU = False
    print("⚠️  GPU monitoring não disponível")


class PerformanceTest:
    def __init__(self):
        self.results = []
        self.processes = []
        self.video_path = "prepared.flv"
        
        # Configurações de teste
        self.cameras_variants = [1, 5, 10]
        self.fps_variants = [5, 10, 15]
        self.model_variants = ["yolov8n.pt", "yolov8s.pt", "yolov8m.pt"]
        

        # self.cameras_variants = [10]
        # self.fps_variants = [15]
        # self.model_variants = ["yolov8m.pt"]

        # Tempo de cada teste em segundos
        self.test_duration = 120  # 2 minutos por teste
        
        # Diretório para salvar resultados
        self.test_dir = f"test_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        os.makedirs(self.test_dir, exist_ok=True)
        print(f"📁 Diretório de resultados: {self.test_dir}/")
        
        # Arquivo consolidado
        self.consolidated_file = os.path.join(self.test_dir, "all_results.json")
        
    def start_process(self, cmd, name):
        """Inicia processo em background"""
        print(f"  Iniciando {name}...")
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid
        )
        self.processes.append((proc, name))
        return proc
    
    def kill_by_name(self, process_name):
        """Mata processos por nome usando pkill"""
        try:
            subprocess.run(['pkill', '-9', '-f', process_name], 
                         stdout=subprocess.DEVNULL, 
                         stderr=subprocess.DEVNULL)
        except:
            pass
    
    def kill_by_port(self, port):
        """Mata processo que está usando uma porta específica"""
        try:
            result = subprocess.run(
                f"lsof -ti:{port} | xargs kill -9",
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except:
            pass
    
    def stop_all_processes(self):
        """Para todos os processos com kill MUITO agressivo"""
        print("\n🛑 Parando processos...")
        
        # Tenta matar cada processo registrado
        for proc, name in self.processes:
            try:
                pid = proc.pid
                print(f"  Matando {name} (PID {pid})...")
                
                # Tentativa 1: SIGTERM
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                    proc.wait(timeout=2)
                    print(f"    ✓ Morreu com SIGTERM")
                    continue
                except subprocess.TimeoutExpired:
                    print(f"    ⚠️  Não respondeu ao SIGTERM")
                except Exception as e:
                    print(f"    ⚠️  SIGTERM falhou: {e}")
                
                # Tentativa 2: SIGKILL no grupo
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                    proc.wait(timeout=1)
                    print(f"    ✓ Morreu com SIGKILL (grupo)")
                    continue
                except Exception as e:
                    print(f"    ⚠️  SIGKILL grupo falhou: {e}")
                
                # Tentativa 3: SIGKILL direto
                try:
                    os.kill(pid, signal.SIGKILL)
                    proc.wait(timeout=1)
                    print(f"    ✓ Morreu com SIGKILL (direto)")
                    continue
                except Exception as e:
                    print(f"    ⚠️  SIGKILL direto falhou: {e}")
                
                # Tentativa 4: proc.kill()
                try:
                    proc.kill()
                    proc.wait(timeout=1)
                    print(f"    ✓ Morreu com proc.kill()")
                except Exception as e:
                    print(f"    ✗ Processo resistiu a tudo: {e}")
                    
            except Exception as e:
                print(f"  ✗ Erro fatal matando {name}: {e}")
        
        self.processes = []
        
        # FALLBACK AGRESSIVO: mata por nome e porta
        print("  🔪 Fallback: matando por nome e porta...")
        
        # Kill uvicorn de várias formas
        for pattern in ["uvicorn", "app.main:app", "app.main"]:
            try:
                subprocess.run(['pkill', '-9', '-f', pattern], 
                             timeout=2,
                             stdout=subprocess.DEVNULL, 
                             stderr=subprocess.DEVNULL)
            except:
                pass
        
        # Kill metrics server
        try:
            subprocess.run(['pkill', '-9', '-f', 'metrics_server.py'], 
                         timeout=2,
                         stdout=subprocess.DEVNULL, 
                         stderr=subprocess.DEVNULL)
        except:
            pass
        
        # Kill por porta
        for port in [8000, 8080]:
            try:
                subprocess.run(f"lsof -ti:{port} | xargs kill -9 2>/dev/null",
                             shell=True,
                             timeout=2,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            except:
                pass
        
        # Kill TODOS os ffmpeg
        try:
            subprocess.run(['pkill', '-9', 'ffmpeg'],
                         timeout=2,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        except:
            pass
        
        time.sleep(1)
        print("  ✓ Limpeza completa")
    
    def wait_for_service(self, url, max_wait=30):
        """Aguarda serviço estar disponível"""
        for _ in range(max_wait):
            try:
                requests.get(url, timeout=1)
                return True
            except:
                time.sleep(1)
        return False
    
    def start_metrics_server(self):
        """Inicia servidor de métricas"""
        self.start_process("python3 metrics_server.py", "Metrics Server")
        if not self.wait_for_service("http://localhost:8080/metrics"):
            raise Exception("Metrics server não iniciou")
        time.sleep(1)
    
    def start_main_app(self):
        """Inicia aplicação principal"""
        self.start_process("uvicorn app.main:app --host 0.0.0.0 --port 8000", "Main App")
        if not self.wait_for_service("http://localhost:8000"):
            raise Exception("Main app não iniciou")
        time.sleep(2)
    
    def start_ffmpeg_streams(self, num_cameras):
        """Inicia streams FFMPEG"""
        print(f"  Iniciando {num_cameras} streams FFMPEG...")
        for i in range(1, num_cameras + 1):
            cmd = f'ffmpeg -re -stream_loop -1 -i "{self.video_path}" -c:v copy -c:a copy -f flv "rtmp://localhost/stream/{i}"'
            self.start_process(cmd, f"FFMPEG-{i}")
            time.sleep(0.2)
        time.sleep(3)  # Aguarda streams estabilizarem
    
    def start_monitoring(self, num_cameras, fps, model):
        """Envia requisições para monitorar câmeras"""
        print(f"  Iniciando monitoramento de {num_cameras} câmeras...")
        
        camera_ids = list(range(1, num_cameras + 1))
        
        payload = {
            "camera_ids": camera_ids,
            "device": "cuda" if HAS_GPU else "cpu",
            "tracker_model": "botsort.yaml",
            "classes": ["car", "truck", "bus", "person"],
            "detection_model_path": model,
            "frames_per_second": fps,
            "frames_before_disappearance": 5,
            "confidence_threshold": 0.50,
            "iou": 0.5,
            "min_track_frames": 5
        }
        
        try:
            response = requests.post(
                "http://localhost:8000/monitor/batch",
                json=payload,
                timeout=30
            )
            if response.status_code == 200:
                print(f"  ✓ Monitoramento iniciado")
                return True
            else:
                print(f"  ✗ Erro ao iniciar: {response.status_code}")
                return False
        except Exception as e:
            print(f"  ✗ Erro: {e}")
            return False
    
    def collect_system_metrics(self, duration):
        """Coleta métricas do sistema durante o teste"""
        print(f"  Coletando métricas por {duration}s...")
        
        cpu_samples = []
        ram_samples = []
        gpu_samples = []
        vram_samples = []
        
        start_time = time.time()
        sample_interval = 2  # amostra a cada 2 segundos
        
        while time.time() - start_time < duration:
            # CPU e RAM
            cpu_samples.append(psutil.cpu_percent(interval=1))
            ram_samples.append(psutil.virtual_memory().percent)
            
            # GPU e VRAM
            if HAS_GPU:
                try:
                    handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                    gpu_util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    gpu_samples.append(gpu_util.gpu)
                    
                    mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    vram_percent = (mem_info.used / mem_info.total) * 100
                    vram_samples.append(vram_percent)
                except:
                    pass
            
            time.sleep(sample_interval - 1)  # já usou 1s no cpu_percent
        
        return {
            "cpu_avg": round(sum(cpu_samples) / len(cpu_samples), 2) if cpu_samples else 0,
            "cpu_max": round(max(cpu_samples), 2) if cpu_samples else 0,
            "ram_avg": round(sum(ram_samples) / len(ram_samples), 2) if ram_samples else 0,
            "ram_max": round(max(ram_samples), 2) if ram_samples else 0,
            "gpu_avg": round(sum(gpu_samples) / len(gpu_samples), 2) if gpu_samples else 0,
            "gpu_max": round(max(gpu_samples), 2) if gpu_samples else 0,
            "vram_avg": round(sum(vram_samples) / len(vram_samples), 2) if vram_samples else 0,
            "vram_max": round(max(vram_samples), 2) if vram_samples else 0,
        }
    
    def get_metrics_from_server(self):
        """Obtém métricas do servidor"""
        try:
            response = requests.get("http://localhost:8080/metrics", timeout=5)
            return response.json()
        except:
            return {}
    
    def reset_metrics_server(self):
        """Reseta métricas no servidor"""
        try:
            requests.post("http://localhost:8080/reset", timeout=5)
        except:
            pass
    
    def stop_monitoring(self):
        """Para monitoramento de todas as câmeras"""
        try:
            requests.post("http://localhost:8000/stop/all", timeout=10)
        except:
            pass
        time.sleep(2)
    
    def run_single_test(self, num_cameras, fps, model):
        """Executa um teste único"""
        print(f"\n{'='*60}")
        print(f"🧪 TESTE: {num_cameras} câmeras | {fps} FPS | {model}")
        print(f"{'='*60}")
        
        test_start = time.time()
        
        try:
            # 1. Reset métricas
            self.reset_metrics_server()
            
            # 2. Inicia streams FFMPEG
            self.start_ffmpeg_streams(num_cameras)
            
            # 3. Inicia monitoramento
            if not self.start_monitoring(num_cameras, fps, model):
                print("❌ Falha ao iniciar monitoramento")
                return None
            
            # 4. Aguarda 10s para estabilizar
            print("  Aguardando estabilização (10s)...")
            time.sleep(10)
            
            # 5. Coleta métricas durante o teste
            system_metrics = self.collect_system_metrics(self.test_duration)
            
            # 6. Obtém métricas do servidor
            app_metrics = self.get_metrics_from_server()
            
            # 7. Para monitoramento
            self.stop_monitoring()
            
            test_duration = time.time() - test_start
            
            result = {
                "timestamp": datetime.now().isoformat(),
                "config": {
                    "cameras": num_cameras,
                    "fps": fps,
                    "model": model
                },
                "duration_seconds": round(test_duration, 2),
                "system": system_metrics,
                "app": app_metrics,
            }
            
            print(f"\n📊 Resultados:")
            print(f"  • Eventos detectados: {app_metrics.get('total_events', 0)}")
            print(f"  • FPS médio: {app_metrics.get('avg_fps', 0)}")
            print(f"  • Latência média: {app_metrics.get('avg_latency', 0)}ms")
            print(f"  • CPU média: {system_metrics['cpu_avg']}% (max: {system_metrics['cpu_max']}%)")
            print(f"  • RAM média: {system_metrics['ram_avg']}% (max: {system_metrics['ram_max']}%)")
            if HAS_GPU:
                print(f"  • GPU média: {system_metrics['gpu_avg']}% (max: {system_metrics['gpu_max']}%)")
                print(f"  • VRAM média: {system_metrics['vram_avg']}% (max: {system_metrics['vram_max']}%)")
            
            return result
            
        except Exception as e:
            print(f"❌ Erro no teste: {e}")
            return None
        
        finally:
            # Para streams FFMPEG com kill agressivo
            print("  Parando streams FFMPEG...")
            for proc, name in self.processes[:]:
                if "FFMPEG" in name:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)  # Força SIGKILL direto
                        proc.wait(timeout=2)
                    except:
                        try:
                            proc.kill()
                            proc.wait(timeout=1)
                        except:
                            pass
                    self.processes.remove((proc, name))
            
            # Fallback: mata qualquer ffmpeg que ficou pendurado
            self.kill_by_name("ffmpeg")
            time.sleep(1)
    
    def run_all_tests(self):
        """Executa todos os testes"""
        print("\n" + "="*60)
        print("🚀 INICIANDO TESTES DE DESEMPENHO")
        print("="*60)
        
        # Verifica vídeo
        if not os.path.exists(self.video_path):
            print(f"❌ Vídeo não encontrado: {self.video_path}")
            return
        
        try:
            # Inicia serviços base
            print("\n📦 Iniciando serviços base...")
            self.start_metrics_server()
            self.start_main_app()
            
            # Calcula total de testes
            total_tests = len(self.cameras_variants) * len(self.fps_variants) * len(self.model_variants)
            current_test = 0
            
            print(f"\n📋 Total de testes: {total_tests}")
            print(f"⏱️  Tempo estimado: ~{(total_tests * self.test_duration) / 60:.0f} minutos")
            
            # Executa todos os testes
            for num_cameras in self.cameras_variants:
                for fps in self.fps_variants:
                    for model in self.model_variants:
                        current_test += 1
                        print(f"\n[{current_test}/{total_tests}]")
                        
                        result = self.run_single_test(num_cameras, fps, model)
                        if result:
                            self.results.append(result)
                            # Salva individual + consolidado após cada teste
                            self.save_individual_result(result)
                            self.save_consolidated_results(final=False)
                        
                        # Pausa entre testes
                        if current_test < total_tests:
                            print("\n⏸️  Pausa de 5s entre testes...")
                            time.sleep(5)
            
            # Salva resultados finais
            self.save_consolidated_results(final=True)
            
        finally:
            self.stop_all_processes()
    
    def save_individual_result(self, result):
        """Salva resultado individual de um teste"""
        cfg = result['config']
        model_name = cfg['model'].replace('.pt', '')
        filename = f"{cfg['cameras']}cam_{cfg['fps']}fps_{model_name}.json"
        filepath = os.path.join(self.test_dir, filename)
        
        with open(filepath, 'w') as f:
            json.dump(result, f, indent=2)
        
        print(f"  💾 Resultado individual: {filename}")
    
    def save_consolidated_results(self, final=False):
        """Salva/atualiza arquivo consolidado com todos os resultados"""
        if not self.results:
            return
        
        with open(self.consolidated_file, 'w') as f:
            json.dump({
                "test_info": {
                    "test_directory": self.test_dir,
                    "total_tests_completed": len(self.results),
                    "total_tests_planned": len(self.cameras_variants) * len(self.fps_variants) * len(self.model_variants),
                    "test_duration_seconds": self.test_duration,
                    "last_updated": datetime.now().isoformat(),
                    "status": "completed" if final else "in_progress"
                },
                "results": self.results
            }, f, indent=2)
        
        status = "✅ Consolidado FINAL" if final else "💾 Consolidado atualizado"
        print(f"  {status}: all_results.json")
        # Imprime resumo
        print("\n" + "="*60)
        print("📈 RESUMO DOS TESTES")
        print("="*60)
        print(f"📁 Diretório: {self.test_dir}/")
        print(f"📄 Consolidado: all_results.json\n")
        
        for r in self.results:
            cfg = r['config']
            app = r['app']
            sys = r['system']
            print(f"\n{cfg['cameras']} cams | {cfg['fps']} FPS | {cfg['model']}:")
            print(f"  Eventos: {app.get('total_events', 0)} | "
                  f"FPS: {app.get('avg_fps', 0)} | "
                  f"Latência: {app.get('avg_latency', 0)}ms")
            print(f"  CPU: {sys['cpu_avg']}% | RAM: {sys['ram_avg']}%", end="")
            if HAS_GPU:
                print(f" | GPU: {sys['gpu_avg']}% | VRAM: {sys['vram_avg']}%")
            else:
                print()


def main():
    print("\n🔬 NUVYolo Performance Test\n")
    
    tester = PerformanceTest()
    
    try:
        tester.run_all_tests()
    except KeyboardInterrupt:
        print("\n\n⚠️  Teste interrompido pelo usuário")
        print("💾 Salvando resultados parciais...")
        tester.save_consolidated_results(final=True)
    except Exception as e:
        print(f"\n\n❌ Erro fatal: {e}")
        if tester.results:
            print("💾 Salvando resultados parciais...")
            tester.save_consolidated_results(final=True)
    finally:
        tester.stop_all_processes()
        
        # Verificação final - kill agressivo se ainda houver processos
        time.sleep(1)
        print("  Verificação final...")
        tester.kill_by_name("uvicorn")
        tester.kill_by_name("metrics_server")
        tester.kill_by_name("ffmpeg")
        tester.kill_by_port(8000)
        tester.kill_by_port(8080)
        
        # Verificar se ainda há processos
        time.sleep(1)
        try:
            check_uvicorn = subprocess.run(
                "ps aux | grep -E 'uvicorn|metrics_server' | grep -v grep",
                shell=True,
                capture_output=True,
                text=True
            )
            if check_uvicorn.stdout.strip():
                print("\n⚠️  AVISO: Ainda há processos rodando:")
                print("  Execute manualmente: pkill -9 -f uvicorn && pkill -9 -f metrics_server")
        except:
            pass
        
        print("\n✅ Teste finalizado\n")


if __name__ == "__main__":
    main()

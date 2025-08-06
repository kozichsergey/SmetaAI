"""
Менеджер прогресса для AI-оптимизации
Управляет статусом и логированием процесса оптимизации
"""

import json
import logging
from datetime import datetime
from pathlib import Path
import time # Added for time.sleep

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ProgressManager:
    def __init__(self):
        self.progress_file = "ai_progress.json"
        self.log_file = "ai_optimization_log.json"
        # Сбрасываем статус при запуске, чтобы не было "зависших" процессов
        self.reset_progress()

    def _get_default_progress(self):
        return {
            "is_running": False,
            "current_task": None, # 'ingest', 'optimize', 'calculate'
            "status": "idle", # 'running', 'success', 'error', 'idle'
            "message": "Система готова",
            "progress_percent": 0,
            "start_time": None,
            "last_update": datetime.now().isoformat(),
            "total_batches": 0,
            "current_batch": 0
        }

    def reset_progress(self):
        self._save_progress(self._get_default_progress())
        
    def start_task(self, task_name, message):
        """Начинает отслеживание новой задачи."""
        progress = {
            "is_running": True,
            "current_task": task_name,
            "status": "running",
            "message": message,
            "progress_percent": 0,
            "start_time": datetime.now().isoformat(),
            "last_update": datetime.now().isoformat(),
            "total_batches": 0,
            "current_batch": 0
        }
        self._save_progress(progress)
        self._add_log_entry(task_name, "start", message)

    def update_progress(self, percent, message):
        """Обновляет прогресс текущей задачи."""
        progress = self.get_progress()
        if not progress['is_running']:
            return
            
        progress['progress_percent'] = percent
        progress['message'] = message
        progress['last_update'] = datetime.now().isoformat()
        self._save_progress(progress)

    def update_batch_progress(self, current_batch, total_batches, base_percent=20):
        """Обновляет прогресс на основе обработки батчей."""
        progress = self.get_progress()
        if not progress['is_running']:
            return
        
        # Рассчитываем процент выполнения батчей
        batch_percent = (current_batch / total_batches) * (95 - base_percent)
        total_percent = base_percent + batch_percent

        progress['progress_percent'] = int(total_percent)
        progress['message'] = f"Обработка AI-батча {current_batch}/{total_batches}"
        progress['total_batches'] = total_batches
        progress['current_batch'] = current_batch
        progress['last_update'] = datetime.now().isoformat()
        self._save_progress(progress)

    def complete_task(self, message):
        """Завершает задачу, устанавливая статус 'success'."""
        progress = self.get_progress()
        if not progress['is_running']:
            return

        progress['is_running'] = False
        progress['status'] = 'success'
        progress['progress_percent'] = 100
        progress['message'] = message
        progress['current_task'] = None
        progress['last_update'] = datetime.now().isoformat()
        self._save_progress(progress)
        self._add_log_entry(progress.get('current_task', 'unknown'), "success", message)
        logger.info(f"Task completed successfully: {message}")
        
    def fail_task(self, error_message):
        """Завершает текущую задачу с ошибкой."""
        progress = self.get_progress()
        if not progress['is_running']:
            return

        progress['is_running'] = False # Останавливаем процесс
        progress['status'] = 'error'
        progress['message'] = error_message
        self._save_progress(progress)
        self._add_log_entry(progress['current_task'], "error", error_message)
        
    def get_progress(self):
        """Получает текущий прогресс из файла."""
        try:
            if Path(self.progress_file).exists():
                with open(self.progress_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"Ошибка чтения файла прогресса: {e}")
        return self._get_default_progress() # Возвращаем дефолтное состояние в случае ошибки

    def is_running(self):
        """Проверяет, запущена ли какая-либо задача."""
        return self.get_progress().get('is_running', False)

    def get_logs(self):
        """Получает историю логов"""
        return self._load_logs()
    
    def _load_progress(self):
        """Загружает данные прогресса"""
        try:
            if Path(self.progress_file).exists():
                with open(self.progress_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки прогресса: {e}")
        
        return None
    
    def _save_progress(self, progress_data):
        """Сохраняет данные прогресса"""
        try:
            with open(self.progress_file, 'w', encoding='utf-8') as f:
                json.dump(progress_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения прогресса: {e}")
    
    def _load_logs(self):
        """Загружает историю логов"""
        try:
            if Path(self.log_file).exists():
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки логов: {e}")
        
        return {"entries": []}
    
    def _save_logs(self, logs_data):
        """Сохраняет историю логов"""
        try:
            with open(self.log_file, 'w', encoding='utf-8') as f:
                json.dump(logs_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения логов: {e}")
    
    def _add_log_entry(self, task_name, status, message):
        """Добавляет запись в лог."""
        try:
            logs = self._load_logs()
            
            entry = {
                "timestamp": datetime.now().isoformat(),
                "task_name": task_name, # Added task_name to log entry
                "status": status,
                "message": message
            }
            
            if "entries" not in logs:
                logs["entries"] = []
            
            logs["entries"].append(entry)
            
            # Ограничиваем количество записей (последние 100)
            if len(logs["entries"]) > 100:
                logs["entries"] = logs["entries"][-100:]
            
            self._save_logs(logs)
            
        except Exception as e:
            logger.error(f"Ошибка добавления записи в лог: {e}") 
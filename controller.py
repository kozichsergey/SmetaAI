import threading
import time
import logging
from pathlib import Path
from datetime import datetime
import json # Added for json.load
from threading import Thread # Added for Thread
from werkzeug.utils import secure_filename

# Импортируем наши классы для работы с данными
from ingest import SmetaIngest
from optimize_brain import BrainOptimizer
from calculate import SmetaCalculator
from config import Config
from progress_manager import ProgressManager
from assistant_manager import AssistantManager # <--- Добавил импорт

logger = logging.getLogger(__name__)

class SmetaAIController:
    def __init__(self, app):
        self.app = app
        self.input_dir = Path("input")
        self.calculate_dir = Path("calculate") 
        self.output_dir = Path("output")
        self.raw_data_file = "raw_data.json"
        self.brain_file = "brain.json"
        self.progress_manager = ProgressManager()
        self.config = Config()
        self.assistant_manager = AssistantManager() # <--- Создаем один раз
        self.current_task_thread = None
        self._task_cancelled = False

    def _run_task(self, task_function, *args):
        self._task_cancelled = False
        try:
            task_function(*args)
        except Exception as e:
            if self._task_cancelled:
                self.app.logger.info("Task was cancelled by user.")
                self.progress_manager.update_progress(0, 'Задача отменена пользователем.')
            else:
                self.app.logger.error(f"Error in background task: {e}", exc_info=True)
                self.progress_manager.complete_task(f"Ошибка: {e}")
        finally:
            self.current_task_thread = None

    def start_task_async(self, task_function, *args):
        if self.current_task_thread and self.current_task_thread.is_alive():
            raise RuntimeError("Другая задача уже выполняется.")
        self.current_task_thread = threading.Thread(target=self._run_task, args=(task_function, *args))
        self.current_task_thread.start()

    def cancel_current_task(self):
        # Проверяем и через thread, и через progress_manager
        is_thread_alive = self.current_task_thread and self.current_task_thread.is_alive()
        is_task_running = self.progress_manager.is_running()
        
        if is_thread_alive or is_task_running:
            self.app.logger.info("Cancellation flag set for the current task.")
            self._task_cancelled = True
            
            # Если задача ещё выполняется, обновляем статус
            if is_task_running:
                self.progress_manager.fail_task("Задача отменена пользователем.")
        else:
            raise RuntimeError("Нет активной задачи для отмены.")

    def _get_new_files_for_processing(self):
        """
        Определяет файлы, которые нужно обработать (новые или измененные).
        Возвращает список Path объектов.
        """
        input_folder = Path("input")
        raw_data_file = Path("raw_data.json")
        
        # Получаем все Excel файлы
        all_files = [f for f in input_folder.glob("*.xlsx") if not f.name.startswith('~')]
        
        # Если raw_data.json не существует, обрабатываем все файлы
        if not raw_data_file.exists():
            self.app.logger.info(f"raw_data.json не найден. Обрабатываем все {len(all_files)} файлов.")
            return all_files
        
        # Загружаем метаданные обработанных файлов
        try:
            with open(raw_data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            processed_files_metadata = data.get('metadata', {}).get('file_metadata', {})
        except Exception as e:
            self.app.logger.error(f"Ошибка чтения raw_data.json: {e}. Обрабатываем все файлы.")
            return all_files
        
        new_files = []
        for file_path in all_files:
            file_name = file_path.name
            
            # Если файл не обработан, добавляем его
            if file_name not in processed_files_metadata:
                new_files.append(file_path)
                continue
            
            # Проверяем, изменился ли файл
            try:
                current_metadata = self._get_file_metadata(file_path)
                stored_metadata = processed_files_metadata[file_name]
                
                # Сравниваем хеш файла
                if current_metadata['hash'] != stored_metadata.get('hash'):
                    self.app.logger.info(f"Файл {file_name} изменился. Добавляем к обработке.")
                    new_files.append(file_path)
                else:
                    self.app.logger.info(f"Файл {file_name} уже обработан и не изменился. Пропускаем.")
            except Exception as e:
                self.app.logger.error(f"Ошибка проверки метаданных для {file_name}: {e}. Добавляем к обработке.")
                new_files.append(file_path)
        
        self.app.logger.info(f"Найдено {len(new_files)} новых/измененных файлов из {len(all_files)} общих.")
        return new_files
    
    def _get_file_metadata(self, file_path):
        """Получает метаданные файла для сравнения."""
        import hashlib
        
        stat = file_path.stat()
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        
        return {
            'size': stat.st_size,
            'modified_time': stat.st_mtime,
            'hash': hash_md5.hexdigest()
        }

    def start_ingest_async(self):
        # Теперь передаем assistant_manager в ingest
        ingest_instance = SmetaIngest(self.progress_manager, self.assistant_manager, self.get_cancellation_token)
        # Получаем только новые файлы для обработки
        files_to_process = self._get_new_files_for_processing()
        
        if not files_to_process:
            self.progress_manager.complete_task("Нет новых файлов для обработки.")
            return
            
        self.start_task_async(ingest_instance.process_files, files_to_process)

    def start_optimize_async(self):
        optimizer = BrainOptimizer(self.progress_manager, self.get_cancellation_token)
        self.start_task_async(optimizer.optimize)

    def start_calculate_async(self):
        calculator = SmetaCalculator(self.progress_manager, self.get_cancellation_token)
        self.start_task_async(calculator.calculate_all)
        
    def get_cancellation_token(self):
        return self._task_cancelled

    def get_system_status(self):
        """Собирает и возвращает общий статус системы для дашборда."""
        
        # Данные из Progress Manager
        status_data = self.progress_manager.get_progress()

        # Дополнительная информация о файлах и данных
        try:
            # Подсчет файлов в input (исключая системные файлы)
            input_files = [f for f in Path("input").glob("*.xlsx") if not f.name.startswith('.')]
            status_data['input_files_count'] = len(input_files)

            if Path("raw_data.json").exists():
                with open("raw_data.json", 'r', encoding='utf-8') as f:
                    raw_data = json.load(f)
                    status_data['raw_data_size'] = len(raw_data.get('records', []))
                    status_data['processed_files_count'] = len(raw_data.get('processed_files', []))
            else:
                status_data['raw_data_size'] = 0
                status_data['processed_files_count'] = 0

            if Path("brain.json").exists():
                with open("brain.json", 'r', encoding='utf-8') as f:
                    brain_data = json.load(f)
                    # brain.json теперь массив, а не объект с items
                    if isinstance(brain_data, list):
                        status_data['brain_size'] = len(brain_data)
                    else:
                        # Обратная совместимость со старым форматом
                    status_data['brain_size'] = len(brain_data.get('items', {}))
            else:
                status_data['brain_size'] = 0
        
        except (IOError, json.JSONDecodeError) as e:
            logger.error(f"Ошибка при чтении файлов статуса: {e}")

        return status_data

    def clear_all_data(self):
        """Удаляет сгенерированные данные (raw_data, brain) для чистого старта."""
        raw_data_file = Path("raw_data.json")
        brain_file = Path("brain.json")
        files_deleted = []
        
        try:
            if raw_data_file.exists():
                raw_data_file.unlink()
                files_deleted.append(raw_data_file.name)
            if brain_file.exists():
                brain_file.unlink()
                files_deleted.append(brain_file.name)
            
            self.progress_manager.reset_progress()
            
            message = f"Файлы {', '.join(files_deleted)} были удалены. База очищена." if files_deleted else "База данных уже чиста."
            logger.info(message)
            return message
        except Exception as e:
            error_message = f"Ошибка при очистке данных: {e}"
            logger.error(error_message)
            raise RuntimeError(error_message)
            
    def get_files_list(self):
        """Собирает списки файлов из всех директорий."""
        base_path = Path('.')
        input_folder = Path('input')
        calculate_folder = Path('calculate')
        output_folder = Path('output')

        # Создаем директории, если они не существуют
        input_folder.mkdir(exist_ok=True)
        calculate_folder.mkdir(exist_ok=True)
        output_folder.mkdir(exist_ok=True)

        try:
            input_files = [f.name for f in input_folder.glob('*.xlsx') if not f.name.startswith('.')]
        except FileNotFoundError:
            input_files = []

        try:
            calculate_files = [f.name for f in calculate_folder.glob('*.xlsx') if not f.name.startswith('.')]
        except FileNotFoundError:
            calculate_files = []

        try:
            output_files = [f.name for f in output_folder.glob('*.xlsx') if not f.name.startswith('.')]
        except FileNotFoundError:
            output_files = []
            
        return {
            'input_files': input_files, 
            'calculate_files': calculate_files, 
            'output_files': output_files
        }

    def get_config(self):
        return self.config.config

    def update_config(self, data):
        """Обновляет конфигурацию."""
        if 'openai_api_key' in data:
            self.config.set_openai_key(data['openai_api_key'])
        if 'openai_model' in data:
            self.config.config['openai_model'] = data['openai_model']
        
        self.config.save_config()
        return "Настройки сохранены."

    # Методы для получения прогресса и логов напрямую из progress_manager
    def get_progress(self):
        """Возвращает текущий прогресс."""
        return self.progress_manager.get_progress()

    def get_logs(self):
        return self.progress_manager.get_logs()
        
    def get_brain_data(self):
        """Возвращает содержимое файла brain.json"""
        brain_path = Path('brain.json')
        if not brain_path.exists():
            return {"error": "Файл brain.json не найден."}, 404
        try:
            with open(brain_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка чтения brain.json: {e}")
            return {"error": "Не удалось прочитать файл brain.json."}, 500 

    def get_status(self):
        """Возвращает текущий статус системы."""
        progress_data = self.progress_manager.get_progress()
        return progress_data
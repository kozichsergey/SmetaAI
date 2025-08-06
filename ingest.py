import pandas as pd
import json
import os
import hashlib
from pathlib import Path
import logging
from datetime import datetime
from assistant_manager import AssistantManager # Новый менеджер
from config import config

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SmetaIngest:
    def __init__(self, progress_manager, assistant_manager, cancellation_token_getter=lambda: False):
        self.progress_manager = progress_manager
        self.assistant_manager = assistant_manager
        self.cancellation_token_getter = cancellation_token_getter
        self.input_folder = Path("input")
        self.raw_data_file = Path("raw_data.json")
        self.responses_dir = Path("output/ai_responses")
        
        # Убедимся, что папки существуют
        self.input_folder.mkdir(exist_ok=True)
        self.responses_dir.mkdir(exist_ok=True, parents=True)

    def _get_file_hash(self, file_path):
        """Вычисляет MD5 хеш файла для проверки изменений."""
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            logger.error(f"Ошибка при вычислении хеша файла {file_path}: {e}")
            return None

    def _get_file_metadata(self, file_path):
        """Получает метаданные файла (размер, дата изменения, хеш)."""
        try:
            stat = file_path.stat()
            return {
                'size': stat.st_size,
                'modified_time': stat.st_mtime,
                'hash': self._get_file_hash(file_path)
            }
        except Exception as e:
            logger.error(f"Ошибка при получении метаданных файла {file_path}: {e}")
            return None

    def _is_file_changed(self, file_path, stored_metadata):
        """Проверяет, изменился ли файл с момента последней обработки."""
        if not stored_metadata:
            return True  # Файл новый
            
        current_metadata = self._get_file_metadata(file_path)
        if not current_metadata:
            return True  # Ошибка получения метаданных, считаем что изменился
            
        return (
            current_metadata['size'] != stored_metadata.get('size') or
            current_metadata['modified_time'] != stored_metadata.get('modified_time') or
            current_metadata['hash'] != stored_metadata.get('hash')
        )

    def _find_files(self):
        """Находит все .xlsx файлы в папке input."""
        files = list(self.input_folder.glob("*.xlsx"))
        logger.info(f"Найдено {len(files)} файлов для обработки в {self.input_folder}")
        return files

    def _load_raw_data(self):
        """Загружает существующие данные или создает новый файл"""
        if self.raw_data_file.exists():
            try:
                with open(self.raw_data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if 'metadata' not in data: data['metadata'] = {}
                    if 'file_metadata' not in data['metadata']: data['metadata']['file_metadata'] = {}
                    if 'records' not in data: data['records'] = []
                    if 'processed_files' not in data: data['processed_files'] = []
                    logger.info(f"Загружено {len(data.get('records', []))} записей из {self.raw_data_file}")
                    return data
            except Exception as e:
                logger.error(f"Ошибка загрузки {self.raw_data_file}: {e}. Создается новый файл.")
        
            logger.info("Создание нового файла raw_data.json")
        return {
            "metadata": {"file_metadata": {}},
            "records": [],
            "processed_files": []
        }
    
    def _parse_and_save_ai_response(self, ai_response_text, file_path):
        """
        Интеллектуально парсит ответ от AI, извлекает JSON и сохраняет его.
        Возвращает список записей или пустой список в случае неудачи.
        """
        if not ai_response_text:
            return []

        # 1. Сохраняем сырой ответ для истории
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        raw_response_filename = self.responses_dir / f"response_{file_path.stem}_{timestamp}.txt"
        with open(raw_response_filename, 'w', encoding='utf-8') as f:
            f.write(ai_response_text)

        # 2. Интеллектуальное извлечение JSON
        try:
            # Ищем начало и конец JSON-массива
            start_index = ai_response_text.find('[')
            end_index = ai_response_text.rfind(']')
            
            if start_index == -1 or end_index == -1:
                raise json.JSONDecodeError("Не найдены границы JSON-массива `[` и `]`.", ai_response_text, 0)
            
            json_text = ai_response_text[start_index : end_index + 1]
            parsed_data = json.loads(json_text)

            # 3. Сохраняем чистый JSON
            clean_response_filename = self.responses_dir / f"response_{file_path.stem}_{timestamp}_clean.json"
            with open(clean_response_filename, 'w', encoding='utf-8') as f:
                json.dump(parsed_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Ответ AI для {file_path.name} успешно распарсен и сохранен.")
            return parsed_data

        except json.JSONDecodeError as e:
            logger.error(f"Ответ AI для {file_path.name} не является валидным JSON даже после очистки. Ошибка: {e}. Сырой ответ сохранен в {raw_response_filename}")
            return []
    
    def _filter_records_with_prices(self, records):
        """
        Фильтрует записи, оставляя только те, где есть хотя бы одна цена.
        Убирает поле quantity, так как оно не нужно.
        """
        filtered_records = []
        for rec in records:
            # Убираем quantity из записи
            if 'quantity' in rec:
                del rec['quantity']
            
            # Проверяем, есть ли хотя бы одна цена
            material_price = rec.get('material_price', 0)
            work_price = rec.get('work_price', 0)
            
            if material_price > 0 or work_price > 0:
                filtered_records.append(rec)
            else:
                logger.info(f"Пропускаем запись без цены: {rec.get('name', 'Без названия')}")
        
        logger.info(f"Отфильтровано {len(filtered_records)} записей с ценами из {len(records)} общих.")
        return filtered_records

    def process_files(self, files_to_process):
        logger.info(f"Начинается обработка {len(files_to_process)} файлов...")
        self.progress_manager.start_task('ingest', f"Найдено {len(files_to_process)} новых файлов для обработки.")
        
        existing_data = self._load_raw_data()
        all_records = existing_data.get("records", [])
        # ИСПРАВЛЕНО: принудительно делаем processed_files_info словарем
        processed_files_raw = existing_data.get("processed_files", {})
        processed_files_info = processed_files_raw if isinstance(processed_files_raw, dict) else {}
        
        newly_processed_files = []

        total_files = len(files_to_process)
        if total_files == 0:
            self.progress_manager.complete_task("Нет новых файлов для обработки.")
            return
        
        # Рассчитываем, какой "вес" имеет каждый файл в общем прогрессе
        file_progress_span = 100 / total_files

        for i, file_path in enumerate(files_to_process):
            if self.cancellation_token_getter():
                logger.info("Процесс загрузки отменен пользователем.")
                self.progress_manager.fail_task("Процесс отменен.")
             return

            base_progress = i * file_progress_span

            try:
                # Новая логика с передачей управления прогрессом
                ai_records = self.assistant_manager.process_file(
                    file_path, 
                    self.progress_manager,
                    base_progress,
                    file_progress_span,
                    self.cancellation_token_getter
                )
                
                if ai_records:
                    # Нормализуем цены, если нужно
                    normalized_records = self._filter_records_with_prices(ai_records)
                    
                    # Добавляем к каждой записи имя исходного файла
                    for record in normalized_records:
                        record['source_file'] = file_path.name
                    
                    all_records.extend(normalized_records)
                    newly_processed_files.append(file_path.name)
                    logger.info(f"Успешно обработан файл {file_path.name}, добавлено {len(normalized_records)} записей.")
                else:
                    logger.warning(f"AI не вернул записи для файла {file_path.name}. Пропускаем.")

            except Exception as e:
                logger.error(f"Критическая ошибка при обработке файла {file_path.name}: {e}", exc_info=True)
                continue

        # Обновляем и сохраняем все данные в конце
        existing_data["records"] = all_records
        
        # Обновляем метаданные для успешно обработанных файлов
        for file_name in newly_processed_files:
            file_path = self.input_folder / file_name
            if file_path.exists():
                 # Предполагается, что у вас есть метод для получения метаданных, например, хэша
                 # Если его нет, можно просто сохранять факт обработки
                 processed_files_info[file_name] = {'last_processed': datetime.now().isoformat()}

        existing_data["processed_files"] = processed_files_info
        
        try:
            with open(self.raw_data_file, "w", encoding="utf-8") as f:
                json.dump(existing_data, f, ensure_ascii=False, indent=2)
            logger.info(f"Файл {self.raw_data_file} успешно сохранен.")
        except IOError as e:
            logger.error(f"Не удалось сохранить {self.raw_data_file}: {e}")

        # Считаем количество реально добавленных записей для корректного сообщения
        initial_records_count = len(self._load_raw_data().get("records", []))
        final_records_count = len(all_records)
        new_records_count = final_records_count - initial_records_count

        self.progress_manager.complete_task(f"Обработка завершена. Добавлено {new_records_count} новых записей.")
        logger.info(f"Обработка завершена. Новых записей: {new_records_count}.")

def main():
    from progress_manager import ProgressManager # Локальный импорт для теста
    class DummyProgressManager:
        def update_progress(self, percent, message): print(f"PROGRESS: {percent}% - {message}")
        def complete_task(self, message): print(f"COMPLETE: {message}")
        def fail_task(self, message): print(f"FAIL: {message}")

    logger.info("Запуск SmetaAI Ingest в тестовом режиме")
    ingester = SmetaIngest(DummyProgressManager(), AssistantManager()) # Передаем AssistantManager
    ingester.process_files()

if __name__ == "__main__":
    main() 
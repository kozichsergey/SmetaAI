import pandas as pd
import json
import logging
from pathlib import Path
from datetime import datetime
import openpyxl
from config import config
import openai
from prompt_loader import load_prompt

logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SmetaCalculator:
    def __init__(self, progress_manager, cancellation_token_getter=lambda: False):
        self.progress_manager = progress_manager
        self.brain_file = Path("brain.json")
        self.calculate_dir = Path("calculate")
        self.output_dir = Path("output")
        self.brain = self._load_brain()
        self.cancellation_token_getter = cancellation_token_getter
        self.client = openai.OpenAI(api_key=config.get_openai_key())
        
        self.calculate_dir.mkdir(exist_ok=True)
        self.output_dir.mkdir(exist_ok=True)

    def _load_brain(self):
        """Загружает базу знаний"""
        if not self.brain_file.exists():
            logger.error(f"Файл базы знаний {self.brain_file} не найден!")
            return []
        try:
            with open(self.brain_file, 'r', encoding='utf-8') as f:
                brain_data = json.load(f)
            
            # Убеждаемся, что работаем с массивом
            if isinstance(brain_data, list):
                logger.info(f"Загружено {len(brain_data)} записей из базы знаний")
                return brain_data
            else:
                # Обратная совместимость со старым форматом
                items = brain_data.get('items', {})
                logger.info(f"Загружено {len(items)} записей из базы знаний (старый формат)")
                return list(items.values())
                
        except Exception as e:
            logger.error(f"Ошибка загрузки базы знаний: {e}")
            return []
            
    def _find_best_match_in_brain(self, item_name, brain_items):
        """Ищет лучшее совпадение в базе знаний через AI"""
        if not brain_items or not item_name:
            return None

        try:
            # Преобразуем brain для передачи в промпт (теперь это массив)
            brain_for_prompt = "\n".join([f"- {item['name']}" for item in brain_items])
            
            # Загружаем промпт из файла
            prompt = load_prompt("calculate_matching", brain_items=brain_for_prompt, item_name=item_name)
            
            response = self.client.chat.completions.create(
                model=config.get_openai_model(),
                messages=[
                    {"role": "system", "content": "Ты - эксперт по сопоставлению данных в строительных сметах. Отвечай только одной строкой - названием из базы."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                timeout=60.0,
            )
            
            best_match_name = response.choices[0].message.content.strip()
            
            # Ищем соответствующую запись в массиве
            for item in brain_items:
                if item['name'] == best_match_name:
                    return item
            
            # Если точного совпадения нет, возвращаем первую запись (fallback)
            logger.warning(f"Точное совпадение не найдено для '{best_match_name}', используем первую запись")
            return brain_items[0] if brain_items else None

        except Exception as e:
            logger.error(f"Ошибка AI-поиска для '{item_name}': {e}")
            return None

    def process_sheet(self, df, brain_items):
        """Обрабатывает лист Excel с batch AI запросом"""
        df = self._ensure_price_columns(df)

        # Находим колонку с наименованиями
        name_col = max(df.columns, key=lambda c: df[c].astype(str).str.len().mean())
        
        # Собираем все наименования для batch обработки
        items_to_process = []
        row_indices = []
        
        for index, row in df.iterrows():
            item_name = row.get(name_col)
            if item_name and not pd.isna(item_name) and len(str(item_name).strip()) > 3:
                items_to_process.append(str(item_name).strip())
                row_indices.append(index)
        
        if not items_to_process:
            logger.info("Нет позиций для обработки в листе")
            return df
        
        # Batch AI запрос для всех позиций сразу
        logger.info(f"Отправляем batch запрос для {len(items_to_process)} позиций")
        matches = self._batch_find_matches(items_to_process, brain_items)
        
        # Применяем найденные совпадения
        for i, (item_name, row_index) in enumerate(zip(items_to_process, row_indices)):
            if i < len(matches) and matches[i]:
                match = matches[i]
                
                if match.get('material_price', 0) > 0:
                    df.loc[row_index, 'Цена материала'] = match['material_price']
                
                if match.get('work_price', 0) > 0:
                    df.loc[row_index, 'Цена работы'] = match['work_price']
        
        return df

    def _batch_find_matches(self, item_names, brain_items):
        """Находит совпадения для списка наименований одним AI запросом"""
        if not item_names or not brain_items:
            return []
        
        try:
            # Формируем списки для промпта
            items_list = "\n".join([f"{i+1}. {name}" for i, name in enumerate(item_names)])
            brain_list = "\n".join([f"- {item['name']}" for item in brain_items])
            
            # Загружаем промпт для batch сопоставления
            prompt = load_prompt("calculate_batch_matching", 
                               items_list=items_list, 
                               brain_list=brain_list)
            
            response = self.client.chat.completions.create(
                model=config.get_openai_model(),
                messages=[
                    {"role": "system", "content": "Ты эксперт по сопоставлению позиций в строительных сметах. Отвечай только JSON массивом."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                timeout=120.0,
            )
            
            result_text = response.choices[0].message.content.strip()
            logger.info(f"AI batch ответ: {result_text[:200]}...")
            
            # Парсим JSON ответ
            matches_data = json.loads(result_text)
            
            # Преобразуем в объекты brain_items
            matches = []
            for match_name in matches_data:
                if match_name:
                    # Ищем соответствующий объект в brain_items
                    found_item = None
                    for brain_item in brain_items:
                        if brain_item['name'] == match_name:
                            found_item = brain_item
                            break
                    matches.append(found_item)
                else:
                    matches.append(None)
            
            logger.info(f"Обработано {len(matches)} совпадений из {len(item_names)} позиций")
            return matches
            
        except Exception as e:
            logger.error(f"Ошибка batch AI поиска: {e}")
            # Fallback на индивидуальные запросы
            logger.info("Переходим на индивидуальную обработку")
            return [self._find_best_match_in_brain(name, brain_items) for name in item_names]

    def _ensure_price_columns(self, df):
        """Проверяет наличие колонок цен и добавляет их, если они отсутствуют."""
        if 'Цена материала' not in df.columns:
            df['Цена материала'] = 0.0
        if 'Цена работы' not in df.columns:
            df['Цена работы'] = 0.0
        return df

    def _find_files_to_process(self):
        """Находит все .xlsx файлы в папке для расчета."""
        files = list(self.calculate_dir.glob("*.xlsx"))
        logger.info(f"Найдено {len(files)} файлов для расчета в папке {self.calculate_dir}")
        return files
    
    def calculate_all(self):
        """Основной метод для расчета всех файлов в папке calculate/"""
        self.progress_manager.start_task("calculate", "Начинаем расчет смет...")
        
        if not self.brain:
            message = "База знаний пуста. Запустите оптимизацию."
            self.progress_manager.fail_task(message)
            return False, message

        files_to_calculate = self._find_files_to_process()
        if not files_to_calculate:
            message = "Нет файлов для расчета в папке calculate/"
            self.progress_manager.complete_task(message)
            return True, message
            
        total_files = len(files_to_calculate)
        processed_count = 0
        
        for i, file_path in enumerate(files_to_calculate):
            # Проверка отмены
            if self.cancellation_token_getter():
                message = "Расчет отменен пользователем."
                self.progress_manager.fail_task(message)
                return False, message
            
            progress = int((i / total_files) * 100)
            self.progress_manager.update_progress(progress, f"Расчет файла {i+1}/{total_files}: {file_path.name}")
            
            if self.process_file(file_path, self.brain):
                processed_count += 1
        
        message = f"Расчет завершен. Успешно обработано {processed_count}/{total_files} файлов."
        self.progress_manager.complete_task(message)
        return True, message 

    def process_file(self, file_path, brain_items):
        """Обрабатывает один файл сметы, добавляя цены из базы знаний."""
        try:
            xls = pd.ExcelFile(file_path)
            output_file_path = self.output_dir / f"РАСЧЕТАННАЯ_{file_path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            
            with pd.ExcelWriter(output_file_path, engine='openpyxl') as writer:
                for sheet_name in xls.sheet_names:
                    df = pd.read_excel(xls, sheet_name=sheet_name)
                    processed_df = self.process_sheet(df, brain_items)
                    processed_df.to_excel(writer, sheet_name=sheet_name, index=False)
            
            logger.info(f"Файл {file_path.name} успешно обработан и сохранен как {output_file_path.name}")
            return True

        except Exception as e:
            logger.error(f"Ошибка при обработке файла {file_path.name}: {e}", exc_info=True)
            return False
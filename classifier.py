"""
AI-Сортировщик для классификации строк из строительных смет
Единственная задача - определить тип каждой строки с помощью OpenAI
"""

import openai
import json
import logging
from config import config
from prompt_loader import load_prompt

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Загрузка конфигурации один раз при импорте модуля
# config = Config() # This line is removed as per the new_code

def batch_classify_rows(row_texts, progress_manager=None):
    if not row_texts:
        return {}
    """
    Классифицирует список строк из строительной сметы с помощью AI в пакетном режиме
    
    Args:
        row_texts (list): Список текстовых строк из сметы
        
    Returns:
        dict: Словарь, где ключ - это строка, а значение - результат классификации
    """
    results = {}
    
    # Сначала классифицируем все с помощью fallback для скорости
    for text in row_texts:
        results[text] = _fallback_classify(text)
    
    # Если AI выключен, возвращаем fallback результаты
    if not config.get_openai_key() or not config.is_ai_enabled():
        logger.info(f"AI выключен. Используется fallback-классификация для {len(row_texts)} строк.")
        return results
        
    logger.info(f"Запуск AI-классификации для {len(row_texts)} уникальных строк...")
    
    try:
        
        # Настройка клиента OpenAI
        client = openai.OpenAI(api_key=config.get_openai_key())
        
        # Разбиваем на батчи (чанки)
        chunk_size = 50 
        chunks = [row_texts[i:i + chunk_size] for i in range(0, len(row_texts), chunk_size)]
        total_chunks = len(chunks)

        for i, chunk in enumerate(chunks):
            # Обновляем прогресс через progress_manager
            if progress_manager:
                progress_manager.update_batch_progress(i + 1, total_chunks, base_percent=20)

            # Создаем один большой промпт для пакетной обработки
            # Формат: numerated list
            input_list = "\n".join([f'{j+1}. "{text}"' for j, text in enumerate(chunk)])
            
            # Загружаем промпт из файла
            prompt = load_prompt("classify_rows", input_list=input_list)
        
        response = client.chat.completions.create(
            model=config.get_openai_model(),
            messages=[
                {"role": "system", "content": "Ты эксперт по строительным сметам. Отвечай только в формате JSON-массива."},
                {"role": "user", "content": prompt}
            ],
            max_completion_tokens=4096, # Заменил max_tokens на max_completion_tokens
            response_format={"type": "json_object"} # Используем JSON-режим
        )
        
        ai_response_str = response.choices[0].message.content
        ai_results = json.loads(ai_response_str)
        
        # Предполагаем, что AI может вернуть results в ключе, например "results" или "classifications"
        if isinstance(ai_results, dict):
            # Ищем ключ, содержащий список
            for key, value in ai_results.items():
                if isinstance(value, list):
                    ai_results = value
                    break

        # Обновляем результаты, полученные от AI
        for item in ai_results:
            row_index = item['id'] - 1
            if 0 <= row_index < len(row_texts):
                original_text = row_texts[row_index]
                results[original_text] = {
                    "type": item.get('type'),
                    "work_type": item.get('work_type')
                }
        
        logger.info(f"AI-классификация успешно завершена для {len(ai_results)} строк.")
        
    except Exception as e:
        logger.error(f"Ошибка при пакетной AI-классификации: {e}. Будут использованы fallback-результаты.")
        # В случае ошибки, fallback-результаты уже в 'results', так что ничего не теряем

    return results

def classify_row(row_text):
    """
    Классифицирует строку из строительной сметы с помощью AI.
    Эта функция остается, так как может использоваться в других частях системы,
    например, в calculate.py для уточнения поиска.
    """
    if not row_text or not row_text.strip():
        return {"type": "info", "work_type": None}
    
    try:
        # Проверяем доступность OpenAI API
        if not config.get_openai_key() or not config.is_ai_enabled():
            # Fallback классификация без AI
            return _fallback_classify(row_text)
        
        # AI-классификация с помощью OpenAI
        return _ai_classify(row_text)
        
    except Exception as e:
        logger.error(f"Ошибка при классификации строки '{row_text}': {e}")
        return _fallback_classify(row_text)

def _ai_classify(row_text):
    """
    AI-классификация с помощью OpenAI
    """
    try:
        
        # Настройка клиента OpenAI
        client = openai.OpenAI(api_key=config.get_openai_key())
        
        # Загружаем промпт из файла
        prompt = load_prompt("classify_single_row", row_text=row_text)
        
        # Вызов OpenAI API
        response = client.chat.completions.create(
            model=config.get_openai_model(),
            messages=[
                {"role": "system", "content": "Ты эксперт по строительным сметам. Отвечай только в формате JSON."},
                {"role": "user", "content": prompt}
            ],
            max_completion_tokens=100
        )
        
        # Парсинг ответа
        ai_response = response.choices[0].message.content.strip()
        
        # Извлекаем JSON из ответа (на случай если AI добавил лишний текст)
        if ai_response.startswith('```json'):
            ai_response = ai_response[7:-3]
        elif ai_response.startswith('```'):
            ai_response = ai_response[3:-3]
        
        result = json.loads(ai_response)
        
        # Валидация результата
        valid_types = ['equipment', 'work', 'complex', 'section', 'info']
        valid_work_types = ['montage', 'demontage', 'pnr', 'delivery', 'project', 'general']
        
        if result.get('type') not in valid_types:
            logger.warning(f"Неизвестный тип '{result.get('type')}' для строки '{row_text}'")
            return _fallback_classify(row_text)
        
        if result.get('type') == 'work' and result.get('work_type') not in valid_work_types:
            logger.warning(f"Неизвестный подтип работы '{result.get('work_type')}' для строки '{row_text}'")
            result['work_type'] = 'general'  # Fallback к общим работам
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка AI-классификации для строки '{row_text}': {e}")
        return _fallback_classify(row_text)

def _fallback_classify(row_text):
    """
    Fallback классификация без AI на основе ключевых слов
    """
    text_lower = row_text.lower().strip()
    
    # Ключевые слова для определения типа
    equipment_keywords = ['вентилятор', 'кондиционер', 'насос', 'клапан', 'труба', 'кабель', 'щит', 'панель', 'блок']
    work_keywords = ['монтаж', 'демонтаж', 'установка', 'прокладка', 'подключение', 'наладка', 'пуско-наладка', 'пнр']
    section_keywords = ['раздел', 'глава', 'часть', 'система', 'комплекс']
    
    # Определение типа
    if any(keyword in text_lower for keyword in equipment_keywords):
        return {"type": "equipment", "work_type": None}
    elif any(keyword in text_lower for keyword in work_keywords):
        # Определение подтипа работы
        if 'демонтаж' in text_lower:
            work_type = 'demontage'
        elif 'пнр' in text_lower or 'пуско-наладка' in text_lower or 'наладка' in text_lower:
            work_type = 'pnr'
        elif 'доставка' in text_lower:
            work_type = 'delivery'
        elif 'проект' in text_lower:
            work_type = 'project'
        else:
            work_type = 'montage'
        return {"type": "work", "work_type": work_type}
    elif any(keyword in text_lower for keyword in section_keywords):
        return {"type": "section", "work_type": None}
    else:
        return {"type": "info", "work_type": None} 

def test_openai_connection():
    """Отправляет тестовый запрос к OpenAI для проверки соединения."""
    try:
        api_key = config.get_openai_key()
        
        if not api_key:
            return False, "OpenAI API ключ не найден в конфигурации. Проверьте config.json."

        client = openai.OpenAI(api_key=api_key)
        
        client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": "Say 'test'"}],
            max_tokens=5,
            timeout=10
        )
        return True, "Соединение с OpenAI API успешно установлено."
    except openai.PermissionDeniedError as e:
        error_message = f"Ошибка доступа к OpenAI: {e.body.get('message')} (Код: {e.body.get('code')})"
        logger.error(error_message)
        return False, error_message
    except Exception as e:
        error_message = f"Не удалось подключиться к OpenAI API: {str(e)}"
        logger.error(error_message)
        return False, error_message

# Удаляем get_column_mapping_by_ai и extract_structured_data,
# так как они заменены AssistantManager.

# class OpenAIClassifier остается, если он используется в optimize_brain.py
class OpenAIClassifier:
    """
    Классификатор для определения структуры данных и группировки
    """
    def __init__(self, api_key=None, api_base=None, log_file='ai_progress.json'):
        self.config = config
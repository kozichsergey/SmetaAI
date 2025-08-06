"""
Утилита для загрузки промптов из файлов.
Все промпты хранятся в отдельных файлах для удобного редактирования.
"""

from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def load_prompt(prompt_name, **kwargs):
    """
    Загружает промпт из файла и подставляет переменные.
    
    Args:
        prompt_name: имя файла промпта без расширения (например, "assistant_instructions")
        **kwargs: переменные для подстановки в промпт
    
    Returns:
        str: готовый промпт с подставленными переменными
    """
    prompt_file = Path(f"prompt_{prompt_name}.txt")
    
    if not prompt_file.exists():
        logger.error(f"Файл промпта {prompt_file} не найден!")
        return f"ОШИБКА: Промпт {prompt_name} не найден!"
    
    try:
        with open(prompt_file, 'r', encoding='utf-8') as f:
            prompt_template = f.read()
        
        # Подставляем переменные, если они переданы
        if kwargs:
            prompt = prompt_template.format(**kwargs)
        else:
            prompt = prompt_template
            
        return prompt
        
    except Exception as e:
        logger.error(f"Ошибка при загрузке промпта {prompt_name}: {e}")
        return f"ОШИБКА: Не удалось загрузить промпт {prompt_name}: {e}" 
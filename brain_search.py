"""
Модуль для поиска и сопоставления элементов в базе знаний (brain.json)
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class BrainSearch:
    """
    Класс для поиска соответствий в базе знаний
    """
    
    def __init__(self, brain_file="brain.json"):
        self.brain_file = brain_file
        self.brain_data = {}
        
    def load_brain(self):
        """Загружает базу знаний из файла"""
        try:
            if Path(self.brain_file).exists():
                with open(self.brain_file, 'r', encoding='utf-8') as f:
                    self.brain_data = json.load(f)
                logger.info(f"Загружена база знаний: {len(self.brain_data.get('material_prices', []))} материалов, {len(self.brain_data.get('work_prices', {}))} типов работ")
                return True
            else:
                logger.warning(f"Файл базы знаний {self.brain_file} не найден")
                return False
        except Exception as e:
            logger.error(f"Ошибка загрузки базы знаний: {e}")
            return False
    
    def find_material_price(self, item_name, item_type=None):
        """
        Ищет цену материала по названию
        
        Args:
            item_name (str): Название материала
            item_type (str): Тип элемента для более точного поиска
            
        Returns:
            float or None: Цена материала или None если не найдено
        """
        if not self.brain_data:
            return None
            
        material_prices = self.brain_data.get('material_prices', [])
        
        # Точное совпадение
        for item in material_prices:
            if item.get('name', '').lower() == item_name.lower():
                return item.get('material_price', 0)
        
        # Частичное совпадение
        for item in material_prices:
            item_brain_name = item.get('name', '').lower()
            if item_name.lower() in item_brain_name or item_brain_name in item_name.lower():
                return item.get('material_price', 0)
                
        return None
    
    def find_work_price(self, item_name, work_type=None):
        """
        Ищет цену работы по названию и типу работы
        
        Args:
            item_name (str): Название работы
            work_type (str): Тип работы (montage, demontage, pnr, etc.)
            
        Returns:
            float or None: Цена работы или None если не найдено
        """
        if not self.brain_data:
            return None
            
        work_prices = self.brain_data.get('work_prices', {})
        
        if not work_type:
            work_type = 'general'
            
        work_type_data = work_prices.get(work_type, [])
        
        # Точное совпадение
        for item in work_type_data:
            if item.get('name', '').lower() == item_name.lower():
                return item.get('work_price', 0)
        
        # Частичное совпадение
        for item in work_type_data:
            item_brain_name = item.get('name', '').lower()
            if item_name.lower() in item_brain_name or item_brain_name in item_name.lower():
                return item.get('work_price', 0)
                
        return None
    
    def calculate_jaccard_similarity(self, text1, text2):
        """
        Вычисляет коэффициент Жаккара для двух строк
        
        Args:
            text1 (str): Первая строка
            text2 (str): Вторая строка
            
        Returns:
            float: Коэффициент сходства от 0 до 1
        """
        # Приводим к нижнему регистру и разбиваем на слова
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        # Вычисляем пересечение и объединение
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        if len(union) == 0:
            return 0
            
        return len(intersection) / len(union)
    
    def find_best_match(self, item_name, item_type=None, work_type=None, threshold=0.3):
        """
        Находит лучшее соответствие в базе знаний с использованием нечеткого поиска
        
        Args:
            item_name (str): Название для поиска
            item_type (str): Тип элемента ('equipment', 'work', etc.)
            work_type (str): Тип работы
            threshold (float): Минимальный порог сходства
            
        Returns:
            dict: Информация о найденном соответствии или None
        """
        if not self.brain_data:
            return None
            
        best_match = None
        best_score = 0
        
        # Поиск среди материалов
        if item_type != 'work':
            material_prices = self.brain_data.get('material_prices', [])
            for item in material_prices:
                score = self.calculate_jaccard_similarity(item_name, item.get('name', ''))
                if score > best_score and score >= threshold:
                    best_score = score
                    best_match = {
                        'type': 'material',
                        'name': item.get('name'),
                        'price': item.get('material_price', 0),
                        'score': score
                    }
        
        # Поиск среди работ
        if item_type == 'work' or item_type is None:
            work_prices = self.brain_data.get('work_prices', {})
            search_work_type = work_type or 'general'
            
            work_type_data = work_prices.get(search_work_type, [])
            for item in work_type_data:
                score = self.calculate_jaccard_similarity(item_name, item.get('name', ''))
                if score > best_score and score >= threshold:
                    best_score = score
                    best_match = {
                        'type': 'work',
                        'work_type': search_work_type,
                        'name': item.get('name'),
                        'price': item.get('work_price', 0),
                        'score': score
                    }
        
        return best_match 
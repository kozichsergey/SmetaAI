import json
import logging
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from config import config
from progress_manager import ProgressManager
from prompt_loader import load_prompt
import openai

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BrainOptimizer:
    def __init__(self, progress_manager=None, cancellation_token_getter=lambda: False):
        self.raw_data_path = Path("raw_data.json")
        self.brain_path = Path("brain.json")
        self.progress_manager = progress_manager
        self.cancellation_token_getter = cancellation_token_getter
        self.client = openai.OpenAI(api_key=config.get_openai_key())
        
    def load_raw_data(self):
        """Загружает сырые данные"""
        if not self.raw_data_path.exists():
            logger.error(f"Файл {self.raw_data_path} не найден!")
            return None
            
        try:
            with open(self.raw_data_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                logger.info(f"Загружено {len(data.get('records', []))} записей из {self.raw_data_path}")
                return data
        except Exception as e:
            logger.error(f"Ошибка загрузки {self.raw_data_path}: {e}")
            return None
    
    def _ai_cluster_similar_items(self, records):
        """Кластеризация похожих записей через AI с предварительной группировкой"""
        if not records:
            return {}
        
        if self.progress_manager:
            self.progress_manager.update_progress(30, f"AI кластеризация {len(records)} записей...")
        
        # Предварительная группировка по типам для улучшения кластеризации
        type_groups = self._pre_group_by_type(records)
        all_clusters = {}
        
        try:
            for group_name, group_records in type_groups.items():
                if len(group_records) <= 1:
                    # Если в группе одна запись, создаем индивидуальный кластер
                    for record in group_records:
                        cluster_name = f"{group_name}: {record['name']}"
                        all_clusters[cluster_name] = [record]
                    continue
                
                # Кластеризуем записи внутри группы
                names_list = [f"{i+1}. {rec['name']}" for i, rec in enumerate(group_records)]
                
                # Загружаем промпт для кластеризации
                prompt = load_prompt("optimize_clustering", input_list="\n".join(names_list))
                
                response = self.client.chat.completions.create(
                    model=config.get_openai_model(),
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1
                )
                
                result_text = response.choices[0].message.content.strip()
                logger.info(f"AI ответ для группы {group_name}: {result_text[:100]}...")
                
                # Парсим результат кластеризации для этой группы
                group_clusters = self._parse_clustering_result(result_text, group_records)
                
                # Добавляем кластеры группы в общий результат
                for cluster_name, cluster_records in group_clusters.items():
                    prefixed_name = f"{group_name}: {cluster_name}"
                    all_clusters[prefixed_name] = cluster_records
            
            # Если кластеризация не сработала, создаем fallback
            if not all_clusters:
                logger.warning("AI кластеризация не вернула результатов. Создаем индивидуальные кластеры.")
                all_clusters = self._create_individual_clusters(records)
            
            logger.info(f"Создано {len(all_clusters)} кластеров из {len(type_groups)} групп")
            return all_clusters
            
        except Exception as e:
            logger.error(f"Ошибка AI кластеризации: {e}")
            # Fallback: каждая запись в отдельный кластер
            return self._create_individual_clusters(records)

    def _parse_clustering_result(self, result_text, records):
        """Парсит результат кластеризации от AI"""
        try:
            # Пытаемся распарсить как JSON
            clusters_json = json.loads(result_text)
            clusters = {}
            
            for canonical_name, original_names in clusters_json.items():
                cluster_records = []
                for original_name in original_names:
                    # Ищем запись по имени (убираем номер из начала)
                    clean_name = original_name
                    if '. ' in original_name:
                        parts = original_name.split('. ', 1)
                        if len(parts) == 2 and parts[0].isdigit():
                            clean_name = parts[1]
                    
                    # Ищем соответствующую запись
                    for record in records:
                        if record['name'] == clean_name:
                            cluster_records.append(record)
                            break
                
                if cluster_records:
                    clusters[canonical_name] = cluster_records
            
            logger.info(f"Создано {len(clusters)} кластеров из JSON")
            return clusters
            
        except json.JSONDecodeError:
            logger.warning("Не удалось распарсить JSON, пробуем старый формат")
            # Fallback на старый парсинг
            return self._parse_clustering_result_old_format(result_text, records)

    def _parse_clustering_result_old_format(self, result_text, records):
        """Парсит результат кластеризации в старом формате"""
        clusters = {}
        current_cluster = None
        
        for line in result_text.split('\n'):
            line = line.strip()
            if not line:
                continue
                
            # Ищем заголовки кластеров (например: "**Кластер 1: Вентиляция**")
            if line.startswith('**') and 'кластер' in line.lower():
                current_cluster = line.strip('*').strip()
                clusters[current_cluster] = []
            elif line.startswith(('-', '•', '*')) and current_cluster:
                # Извлекаем номер записи из строки
                try:
                    # Ищем номер в начале строки (например: "- 1. Название")
                    parts = line.split('.', 1)
                    if len(parts) >= 2:
                        num_str = parts[0].strip('- •*').strip()
                        if num_str.isdigit():
                            index = int(num_str) - 1  # Индекс в массиве (начинается с 0)
                            if 0 <= index < len(records):
                                clusters[current_cluster].append(records[index])
                except Exception as e:
                    logger.warning(f"Ошибка парсинга строки кластера: {line}, {e}")
        
        # Убираем пустые кластеры
        clusters = {k: v for k, v in clusters.items() if v}
        
        logger.info(f"Создано {len(clusters)} кластеров")
        return clusters

    def _create_brain_from_clusters(self, clusters):
        """Создает brain.json из кластеров с умной обработкой цен"""
        brain_data = []
        
        for cluster_name, cluster_records in clusters.items():
            if not cluster_records:
                continue
                
            # Берем первую запись как основу
            base_record = cluster_records[0]
            
            # Собираем все варианты цен
            material_prices = [r['material_price'] for r in cluster_records if r.get('material_price', 0) > 0]
            work_prices = [r['work_price'] for r in cluster_records if r.get('work_price', 0) > 0]
            
            # Применяем умную логику обработки цен
            material_result = self._smart_price_calculation(material_prices, "материала", cluster_name)
            work_result = self._smart_price_calculation(work_prices, "работы", cluster_name)
            
            # Создаем запись для brain с расширенной информацией
            brain_record = {
                "name": base_record['name'],
                "unit": base_record.get('unit', ''),
                "material_price": material_result['final_price'],
                "work_price": work_result['final_price'],
                
                # Расширенная информация о ценах
                "price_analysis": {
                    "material": material_result if material_prices else None,
                    "work": work_result if work_prices else None
                },
                
                "cluster_size": len(cluster_records),
                "source_files": list(set(r.get('source_file', '') for r in cluster_records)),
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            
            brain_data.append(brain_record)
        
        return brain_data

    def _smart_price_calculation(self, prices, price_type, item_name):
        """
        Умная обработка цен согласно логике пользователя:
        - 2 цены: если разница ≤25% → среднее, иначе среднее + предупреждение
        - 3 цены: если разница мин-макс ≤25% → среднее, иначе среднее + предупреждение  
        - 4+ цен: отбрасываем крайние, если разница 2й и предпоследней ≤25% → среднее, иначе среднее + предупреждение
        """
        if not prices:
            return {
                'final_price': 0,
                'original_prices': [],
                'used_prices': [],
                'calculation_method': 'no_prices',
                'warning': None,
                'variance_percent': 0
            }
        
        # Сортируем цены
        sorted_prices = sorted(prices)
        original_count = len(prices)
        threshold = config.get_price_variance_threshold()
        
        if original_count == 1:
            return {
                'final_price': round(sorted_prices[0], 2),
                'original_prices': prices,
                'used_prices': sorted_prices,
                'calculation_method': 'single_price',
                'warning': None,
                'variance_percent': 0
            }
        
        elif original_count == 2:
            # 2 цены: проверяем разницу
            min_price, max_price = sorted_prices[0], sorted_prices[1]
            variance = ((max_price - min_price) / min_price) * 100
            
            final_price = round(sum(sorted_prices) / len(sorted_prices), 2)
            warning = f"Перепроверить цену {price_type}!" if variance > threshold else None
            
            return {
                'final_price': final_price,
                'original_prices': prices,
                'used_prices': sorted_prices,
                'calculation_method': 'average_2_prices',
                'warning': warning,
                'variance_percent': round(variance, 1)
            }
        
        elif original_count == 3:
            # 3 цены: проверяем разницу между мин и макс
            min_price, max_price = sorted_prices[0], sorted_prices[2]
            variance = ((max_price - min_price) / min_price) * 100
            
            final_price = round(sum(sorted_prices) / len(sorted_prices), 2)
            warning = f"Перепроверить цену {price_type}!" if variance > threshold else None
            
            return {
                'final_price': final_price,
                'original_prices': prices,
                'used_prices': sorted_prices,
                'calculation_method': 'average_3_prices',
                'warning': warning,
                'variance_percent': round(variance, 1)
            }
        
        else:
            # 4+ цен: отбрасываем крайние
            trimmed_prices = sorted_prices[1:-1]  # Убираем первую и последнюю
            
            if len(trimmed_prices) >= 2:
                min_trimmed, max_trimmed = trimmed_prices[0], trimmed_prices[-1]
                variance = ((max_trimmed - min_trimmed) / min_trimmed) * 100
            else:
                variance = 0
            
            final_price = round(sum(trimmed_prices) / len(trimmed_prices), 2)
            warning = f"Перепроверить цену {price_type}!" if variance > threshold else None
            
            return {
                'final_price': final_price,
                'original_prices': prices,
                'used_prices': trimmed_prices,
                'calculation_method': f'trimmed_average_{original_count}_prices',
                'warning': warning,
                'variance_percent': round(variance, 1),
                'excluded_prices': [sorted_prices[0], sorted_prices[-1]]
            }

    def _create_individual_clusters(self, records):
        """Создает индивидуальный кластер для каждой записи"""
        clusters = {}
        for i, record in enumerate(records):
            cluster_name = f"Кластер {i+1}: {record['name']}"
            clusters[cluster_name] = [record]
        logger.info(f"Создано {len(clusters)} индивидуальных кластеров")
        return clusters

    def _pre_group_by_type(self, records):
        """Предварительная группировка записей по типам оборудования"""
        groups = {
            'Вентиляция': [],
            'Электрика': [],
            'Трубопроводы': [],
            'Крепеж': [],
            'Работы': [],
            'Прочее': []
        }
        
        for record in records:
            name = record['name'].lower()
            
            # Определяем тип по ключевым словам
            if any(word in name for word in ['вентилятор', 'воздуховод', 'решетка', 'клапан', 'шумоглушитель', 'глушитель']):
                groups['Вентиляция'].append(record)
            elif any(word in name for word in ['кабель', 'провод', 'щит', 'автомат', 'розетка', 'выключатель', 'светильник']):
                groups['Электрика'].append(record)
            elif any(word in name for word in ['труба', 'фитинг', 'тройник', 'отвод', 'переход', 'заглушка']):
                groups['Трубопроводы'].append(record)
            elif any(word in name for word in ['болт', 'гайка', 'шайба', 'саморез', 'дюбель', 'анкер', 'крепеж']):
                groups['Крепеж'].append(record)
            elif any(word in name for word in ['монтаж', 'установка', 'демонтаж', 'наладка', 'пуско-наладка', 'работы']):
                groups['Работы'].append(record)
            else:
                groups['Прочее'].append(record)
        
        # Убираем пустые группы
        groups = {k: v for k, v in groups.items() if v}
        
        logger.info(f"Предварительная группировка: {[(k, len(v)) for k, v in groups.items()]}")
        return groups
    
    def save_brain(self, brain_data):
        """Сохраняет brain.json"""
        try:
            with open(self.brain_path, 'w', encoding='utf-8') as f:
                json.dump(brain_data, f, ensure_ascii=False, indent=2)
            logger.info(f"Сохранено {len(brain_data)} записей в {self.brain_path}")
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения {self.brain_path}: {e}")
            return False
    
    def optimize(self):
        """Основной метод оптимизации"""
        logger.info("Starting brain optimization...")
        if self.progress_manager:
            self.progress_manager.start_task("optimize", "Запуск оптимизации базы знаний...")

        try:
            # Проверка отмены
            if self.cancellation_token_getter():
                if self.progress_manager:
                    self.progress_manager.fail_task("Оптимизация отменена пользователем.")
                return

            # Загрузка данных
            raw_data = self.load_raw_data()
            if not raw_data or not raw_data.get('records'):
                if self.progress_manager:
                    self.progress_manager.fail_task("Нет данных для оптимизации.")
                return

            records = raw_data.get('records', [])
            if self.progress_manager:
                self.progress_manager.update_progress(10, f"Загружено {len(records)} записей для оптимизации...")

            # AI кластеризация
            clusters = self._ai_cluster_similar_items(records)
            
            if self.progress_manager:
                self.progress_manager.update_progress(70, f"Создано {len(clusters)} кластеров, формирование базы знаний...")

            # Создание brain.json
            brain_data = self._create_brain_from_clusters(clusters)
            
            if self.progress_manager:
                self.progress_manager.update_progress(90, "Сохранение базы знаний...")

            # Сохранение
            if self.save_brain(brain_data):
                if self.progress_manager:
                    self.progress_manager.complete_task(f"Оптимизация завершена. Создано {len(brain_data)} записей в базе знаний.")
            else:
                if self.progress_manager:
                    self.progress_manager.fail_task("Ошибка сохранения базы знаний.")
                
        except Exception as e:
            logger.error(f"Ошибка оптимизации: {e}", exc_info=True)
            if self.progress_manager:
                self.progress_manager.fail_task(f"Ошибка оптимизации: {e}")

def main():
    """Основная функция для отладки"""
    logger.info("Запуск SmetaAI Brain Optimizer")
    
    optimizer = BrainOptimizer()
    # Для вызова этого метода нужен progress_manager
    # success, message = optimizer.optimize(ProgressManager()) 
    
    # if success:
    #     print(f"\n=== ОТЧЕТ ===")
    #     print(message)
    # else:
    #     print(f"\n=== ОШИБКА ===")
    #     print(message)

if __name__ == "__main__":
    main() 
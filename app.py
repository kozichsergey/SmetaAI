from flask import Flask, render_template, request, jsonify, send_file, Response
from flask_cors import CORS
import logging
from controller import SmetaAIController
from pathlib import Path
import json
import pandas as pd
from datetime import datetime
from io import BytesIO
import os

# --- Настройка ---
# Настройка Flask
app = Flask(__name__)
CORS(app)
# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Создание необходимых директорий при запуске
Path("input").mkdir(exist_ok=True)
Path("calculate").mkdir(exist_ok=True)
Path("output").mkdir(exist_ok=True)
logger.info("Проверено наличие директорий input, calculate, output.")

# Инициализация контроллера
controller = SmetaAIController(app)

# --- Маршруты (Routes) ---

@app.route('/')
def index():
    """Главная страница."""
    return render_template('index.html')

@app.route('/favicon.ico')
def favicon():
    """Отдает пустой ответ для иконки, чтобы избежать ошибок 404 в логах."""
    return Response(status=204)

@app.route('/api/status', methods=['GET'])
def get_status():
    """Возвращает текущий статус системы."""
    return jsonify(controller.get_system_status())

@app.route('/api/ingest', methods=['POST'])
def start_ingest():
    """Запускает процесс загрузки данных."""
    try:
        message = controller.start_ingest_async()
        return jsonify({"message": message}), 202
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409 # 409 Conflict - ресурс занят

@app.route('/api/optimize', methods=['POST'])
def start_optimize():
    """Запускает процесс оптимизации."""
    try:
        message = controller.start_optimize_async()
        return jsonify({"message": message}), 202
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409

@app.route('/api/calculate', methods=['POST'])
def start_calculate():
    """Запускает процесс расчета для ВСЕХ смет в папке 'calculate'."""
    try:
        message = controller.start_calculate_async()
        return jsonify({"message": message}), 202
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409

@app.route('/api/files', methods=['GET'])
def get_files():
    """Возвращает списки файлов."""
    return jsonify(controller.get_files_list())

@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    """Обрабатывает получение и обновление конфигурации."""
    if request.method == 'POST':
        data = request.get_json()
        message = controller.update_config(data)
        return jsonify({"message": message})
    else:
        return jsonify(controller.get_config())

@app.route('/api/ai_logs', methods=['GET'])
def get_ai_logs():
    """Возвращает историю логов."""
    return jsonify(controller.get_logs())

@app.route('/api/brain', methods=['GET'])
def get_brain_data():
    """Возвращает данные базы знаний для отображения в UI."""
    try:
        brain_file = Path("brain.json")
        if not brain_file.exists():
            return jsonify([])
        
        with open(brain_file, 'r', encoding='utf-8') as f:
            brain_data = json.load(f)
        
        # Убеждаемся, что возвращаем массив
        if isinstance(brain_data, list):
            return jsonify(brain_data)
        else:
            # Обратная совместимость со старым форматом
            return jsonify(brain_data.get('items', []))
    
    except Exception as e:
        app.logger.error(f"Error reading brain data: {e}")
        return jsonify({"error": "Failed to load brain data"}), 500

@app.route('/api/brain/edit', methods=['POST'])
def edit_brain():
    """Редактирование записи в базе знаний"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "Нет данных"}), 400
        
        index = data.get('index')
        if index is None or index < 0:
            return jsonify({"error": "Неверный индекс"}), 400
        
        name = data.get('name', '').strip()
        if not name:
            return jsonify({"error": "Наименование обязательно"}), 400
        
        # Читаем текущую базу знаний
        brain_file = 'brain.json'
        if not os.path.exists(brain_file):
            return jsonify({"error": "База знаний не найдена"}), 404
        
        with open(brain_file, 'r', encoding='utf-8') as f:
            brain_data = json.load(f)
        
        if index >= len(brain_data):
            return jsonify({"error": "Запись не найдена"}), 404
        
        # Обновляем запись
        brain_data[index]['name'] = name
        brain_data[index]['unit'] = data.get('unit', '').strip()
        brain_data[index]['material_price'] = float(data.get('material_price', 0))
        brain_data[index]['work_price'] = float(data.get('work_price', 0))
        brain_data[index]['material_price_approved'] = bool(data.get('material_price_approved', False))
        brain_data[index]['work_price_approved'] = bool(data.get('work_price_approved', False))
        brain_data[index]['updated_at'] = datetime.now().isoformat()
        
        # Сохраняем обновленную базу знаний
        with open(brain_file, 'w', encoding='utf-8') as f:
            json.dump(brain_data, f, ensure_ascii=False, indent=2)
        
        return jsonify({"message": "Запись успешно обновлена"})
        
    except Exception as e:
        print(f"Ошибка редактирования записи: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/brain/delete', methods=['POST'])
def delete_brain():
    """Удаление записи из базы знаний"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "Нет данных"}), 400
        
        index = data.get('index')
        if index is None or index < 0:
            return jsonify({"error": "Неверный индекс"}), 400
        
        # Читаем текущую базу знаний
        brain_file = 'brain.json'
        if not os.path.exists(brain_file):
            return jsonify({"error": "База знаний не найдена"}), 404
        
        with open(brain_file, 'r', encoding='utf-8') as f:
            brain_data = json.load(f)
        
        if index >= len(brain_data):
            return jsonify({"error": "Запись не найдена"}), 404
        
        # Удаляем запись
        deleted_item = brain_data.pop(index)
        
        # Сохраняем обновленную базу знаний
        with open(brain_file, 'w', encoding='utf-8') as f:
            json.dump(brain_data, f, ensure_ascii=False, indent=2)
        
        print(f"Удалена запись: {deleted_item.get('name', 'Без названия')}")
        return jsonify({"message": "Запись успешно удалена"})
        
    except Exception as e:
        print(f"Ошибка удаления записи: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/raw_data/edit', methods=['POST'])
def edit_raw_item():
    """Редактирует запись в полной базе данных."""
    try:
        data = request.json
        index = data.get('index')
        name = data.get('name', '').strip()
        unit = data.get('unit', '').strip()
        material_price = float(data.get('material_price', 0))
        work_price = float(data.get('work_price', 0))
        
        if not name:
            return jsonify({"success": False, "error": "Наименование обязательно"}), 400
        
        if material_price == 0 and work_price == 0:
            return jsonify({"success": False, "error": "Должна быть указана хотя бы одна цена"}), 400
        
        raw_data_file = Path("raw_data.json")
        if not raw_data_file.exists():
            return jsonify({"success": False, "error": "Полная база данных не найдена"}), 404
        
        # Загружаем данные
        with open(raw_data_file, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
        
        # Проверяем структуру и индекс
        if not isinstance(raw_data, dict) or 'records' not in raw_data:
            return jsonify({"success": False, "error": "Неверная структура данных"}), 400
        
        records = raw_data['records']
        if not isinstance(records, list) or index < 0 or index >= len(records):
            return jsonify({"success": False, "error": "Неверный индекс записи"}), 400
        
        # Обновляем запись
        records[index]['name'] = name
        records[index]['unit'] = unit
        records[index]['material_price'] = material_price
        records[index]['work_price'] = work_price
        records[index]['updated_at'] = datetime.now().isoformat()
        
        # Сохраняем
        with open(raw_data_file, 'w', encoding='utf-8') as f:
            json.dump(raw_data, f, ensure_ascii=False, indent=2)
        
        app.logger.info(f"Raw data item {index} updated: {name}")
        return jsonify({"success": True, "message": "Запись обновлена"})
        
    except Exception as e:
        app.logger.error(f"Error editing raw data item: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/brain/export', methods=['GET'])
def export_brain():
    """Экспортирует базу знаний в Excel файл."""
    try:
        brain_file = Path('brain.json')
        if not brain_file.exists():
            return jsonify({'error': 'База знаний не найдена'}), 404
        
        with open(brain_file, 'r', encoding='utf-8') as f:
            brain_data = json.load(f)
        
        # Новый формат - массив объектов
        if not isinstance(brain_data, list):
            return jsonify({'error': 'Неверный формат базы знаний'}), 400
        
        # Преобразуем в DataFrame
        rows = []
        for item in brain_data:
            row = {
                'Наименование': item.get('name', ''),
                'Единица измерения': item.get('unit', ''),
                'Цена материала': item.get('material_price', 0),
                'Цена работы': item.get('work_price', 0),
                'Размер кластера': item.get('cluster_size', 1),
                'Источники': ', '.join(item.get('source_files', [])) if isinstance(item.get('source_files'), list) else str(item.get('source_files', ''))
            }
            rows.append(row)
        
        if not rows:
            return jsonify({'error': 'База знаний пуста'}), 400
        
        df = pd.DataFrame(rows)
        
        # Создаем Excel файл
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='База знаний', index=False)
        
        output.seek(0)
        
        return Response(
            output.getvalue(),
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={
                'Content-Disposition': 'attachment; filename=brain_export.xlsx'
            }
        )
        
    except Exception as e:
        app.logger.error(f"Error exporting brain: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/brain/import', methods=['POST'])
def import_brain():
    """Импортирует базу знаний из Excel файла."""
    try:
        file = request.files.get('file')
        if not file:
            return jsonify({'error': 'Файл не загружен'}), 400
        
        df = pd.read_excel(file)
        
        # Проверяем наличие необходимых колонок
        required_columns = ['Наименование']
        for col in required_columns:
            if col not in df.columns:
                return jsonify({'error': f'Отсутствует обязательная колонка: {col}'}), 400
        
        # Преобразуем DataFrame в новый формат
        brain_data = []
        for _, row in df.iterrows():
            name = str(row['Наименование']).strip()
            if not name or name == 'nan':
                continue
                
            item = {
                'name': name,
                'unit': str(row.get('Единица измерения', '')).strip() if pd.notna(row.get('Единица измерения')) else '',
                'material_price': float(row.get('Цена материала', 0)) if pd.notna(row.get('Цена материала')) else 0,
                'work_price': float(row.get('Цена работы', 0)) if pd.notna(row.get('Цена работы')) else 0,
                'cluster_size': int(row.get('Размер кластера', 1)) if pd.notna(row.get('Размер кластера')) else 1,
                'source_files': [s.strip() for s in str(row.get('Источники', '')).split(',') if s.strip()] if pd.notna(row.get('Источники')) else [],
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            
            # Добавляем только записи с хотя бы одной ценой
            if item['material_price'] > 0 or item['work_price'] > 0:
                brain_data.append(item)
        
        if not brain_data:
            return jsonify({'error': 'Не найдено записей с ценами для импорта'}), 400
        
        # Сохраняем в новом формате
        with open('brain.json', 'w', encoding='utf-8') as f:
            json.dump(brain_data, f, ensure_ascii=False, indent=2)
        
        app.logger.info(f"Brain imported: {len(brain_data)} items")
        return jsonify({'success': True, 'count': len(brain_data)})
        
    except Exception as e:
        app.logger.error(f"Error importing brain: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/test_openai', methods=['GET'])
def test_openai():
    """Тестирует соединение с OpenAI."""
    from classifier import test_openai_connection
    success, message = test_openai_connection()
    if success:
        return jsonify({"status": "success", "message": message})
    else:
        return jsonify({"status": "error", "message": message}), 500

@app.route('/api/cancel_task', methods=['POST'])
def cancel_task():
    try:
        controller.cancel_current_task()
        return jsonify({'success': True, 'message': 'Задача отменена'})
    except RuntimeError as e:
        # Если задача уже завершена, это не ошибка
        if "Нет активной задачи для отмены" in str(e):
            return jsonify({'success': True, 'message': 'Нет активной задачи'})
        else:
            app.logger.error(f"Error cancelling task: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    except Exception as e:
        app.logger.error(f"Error cancelling task: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/reset_status', methods=['POST'])
def reset_status():
    """Сбрасывает состояние прогресса в idle."""
    controller.progress_manager.reset_progress()
    return jsonify({"message": "Статус сброшен"}), 200

@app.route('/api/clear_data', methods=['POST'])
def clear_data():
    """Полностью очищает сгенерированные данные (raw_data, brain)."""
    try:
        message = controller.clear_all_data()
        return jsonify({"message": message}), 200
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/raw_data', methods=['GET'])
def get_raw_data():
    raw_file = Path('raw_data.json')
    if not raw_file.exists():
        return jsonify({'records': []})
    with open(raw_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return jsonify({'records': data.get('records', [])})

# --- Main ---
if __name__ == '__main__':
    # Очистка состояния при запуске, если это необходимо
    app.run(debug=True, host='0.0.0.0', port=8000) 
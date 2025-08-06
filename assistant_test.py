import openai
import os
import time
import json
from pathlib import Path
from config import Config

# --- НАСТРОЙКА ---
# Загружаем конфигурацию для получения API-ключа
config = Config()
client = openai.OpenAI(api_key=config.get_openai_key())

# Имя нашего ассистента (чтобы находить его в будущем)
ASSISTANT_NAME = "Smeta Parser Assistant"
ASSISTANT_INSTRUCTIONS = """
Твоя роль: Ты — высококвалифицированный инженер-сметчик, эксперт по анализу данных в Excel.
Твоя задача: Тебе будет предоставлен Excel-файл со строительной сметой. Используй инструмент Code Interpreter для того, чтобы:
1.  Открыть и прочитать содержимое файла с помощью pandas.
2.  Тщательно проанализировать структуру документа, найти основную таблицу с перечнем работ и материалов.
3.  Извлечь из таблицы ВСЕ значащие строки.
4.  Сформировать и вернуть JSON-массив объектов.

Требования к JSON-ответу:
- Твой финальный ответ должен быть ТОЛЬКО JSON-массивом. Никакого лишнего текста, пояснений или форматирования markdown.
- Каждый объект в массиве должен иметь следующие ключи: "name", "unit", "quantity", "material_price", "work_price".
- "name": Полное и точное наименование работы или материала.
- "unit": Единица измерения (например, "шт.", "м2", "компл."). Если не найдено, ставь null.
- "quantity": Количество. Это должно быть число. Если не найдено, ставь 1.
- "material_price": Цена за единицу материала. Это должно быть число. Если это работа или цена отсутствует, ставь 0.
- "work_price": Цена за единицу работы. Это должно быть число. Если это материал или цена отсутствует, ставь 0.

Крайне важно:
- Игнорируй строки с итогами, под-итогами, налогами (НДС), заголовки документа, шапку таблицы, подписи и любую другую служебную информацию, не относящуюся к конкретным позициям сметы.
- Обработай все листы в Excel-файле, если их несколько.
"""

# --- ЛОГИКА АССИСТЕНТА ---

def get_or_create_assistant():
    """Находит существующего ассистента по имени или создает нового."""
    # assistants = client.beta.assistants.list(limit=100)
    # for assistant in assistants.data:
    #     if assistant.name == ASSISTANT_NAME:
    #         print(f"Найден существующий ассистент: {assistant.id}")
    #         return assistant

    print("Создание нового ассистента...")
    assistant = client.beta.assistants.create(
        name=ASSISTANT_NAME,
        instructions=ASSISTANT_INSTRUCTIONS,
        tools=[{"type": "code_interpreter"}],
        model=config.get_openai_model()
    )
    print(f"Ассистент создан: {assistant.id}")
    return assistant

def process_file_with_assistant(file_path: Path, assistant_id: str):
    """
    Обрабатывает один Excel-файл с помощью указанного ассистента.
    """
    if not file_path.exists():
        print(f"Файл не найден: {file_path}")
        return

    print(f"\n--- Обработка файла: {file_path.name} ---")

    # 1. Загружаем файл в OpenAI
    print("1. Загрузка файла в OpenAI...")
    file_object = client.files.create(
        file=file_path.open("rb"),
        purpose='assistants'
    )
    print(f"   Файл загружен, ID: {file_object.id}")

    # 2. Создаем "ветку диалога" (Thread)
    print("2. Создание новой ветки диалога (Thread)...")
    thread = client.beta.threads.create()
    print(f"   Ветка создана, ID: {thread.id}")

    # 3. Добавляем сообщение с файлом в ветку
    print("3. Добавление сообщения с файлом в ветку...")
    client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=f"Проанализируй этот сметный документ и верни результат в формате JSON.",
        attachments=[{"file_id": file_object.id, "tools": [{"type": "code_interpreter"}]}]
    )
    print("   Сообщение добавлено.")

    # 4. Запускаем ассистента на выполнение задачи
    print("4. Запуск ассистента...")
    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant_id,
    )
    print(f"   Ассистент запущен, Run ID: {run.id}")

    # 5. Ждем завершения выполнения
    print("5. Ожидание завершения выполнения (это может занять несколько минут)...")
    while run.status in ['queued', 'in_progress', 'cancelling']:
        time.sleep(5)  # Опрашиваем статус каждые 5 секунд
        run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
        print(f"   ...текущий статус: {run.status}")

    if run.status == 'completed':
        print("   Выполнение успешно завершено!")
        # 6. Получаем сообщения из ветки
        messages = client.beta.threads.messages.list(thread_id=thread.id)
        
        # Ищем последнее сообщение от ассистента
        for message in messages.data:
            if message.role == 'assistant':
                for content_block in message.content:
                    if content_block.type == 'text':
                        response_text = content_block.text.value
                        print("\n--- ПОЛУЧЕН ОТВЕТ ОТ AI ---")
                        print(response_text)
                        
                        # Сохраняем результат в файл для проверки
                        output_file = Path(f"output/ai_responses/assistant_response_{file_path.stem}.json")
                        output_file.parent.mkdir(exist_ok=True)
                        try:
                            # Убираем возможное обрамление ```json ... ```
                            if response_text.startswith("```json"):
                                response_text = response_text[7:-3].strip()
                            
                            parsed_json = json.loads(response_text)
                            with open(output_file, 'w', encoding='utf-8') as f:
                                json.dump(parsed_json, f, ensure_ascii=False, indent=2)
                            print(f"\nРезультат сохранен в: {output_file}")
                        except json.JSONDecodeError:
                            print("\nОШИБКА: Ответ от AI не является валидным JSON.")
                            text_output_file = output_file.with_suffix('.txt')
                            with open(text_output_file, 'w', encoding='utf-8') as f:
                                f.write(response_text)
                            print(f"Сырой ответ сохранен в: {text_output_file}")

                        return # Завершаем после первого найденного ответа
    else:
        print(f"\nОШИБКА: Выполнение завершилось со статусом '{run.status}'.")
        print(run.last_error)


# --- ТОЧКА ВХОДА ---
if __name__ == "__main__":
    # Находим или создаем ассистента
    assistant = get_or_create_assistant()

    # Укажите здесь путь к файлу, который хотите протестировать
    # Например, первый .xlsx файл из папки input
    input_dir = Path("input")
    test_files = list(input_dir.glob("*.xlsx"))

    if not test_files:
        print("\nВНИМАНИЕ: Не найдено .xlsx файлов в папке 'input' для теста.")
    else:
        # Берем первый найденный файл для теста
        file_to_process = test_files[0]
        process_file_with_assistant(file_to_process, assistant.id) 
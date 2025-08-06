import openai
import json
import time
from pathlib import Path
import logging
from config import Config
from prompt_loader import load_prompt

config = Config()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ASSISTANT_NAME = "Smeta Parser Assistant"

class AssistantManager:
    ASSISTANT_NAME = "Smeta Parser Assistant"
    ASSISTANT_ID_FILE = Path("assistant_id.txt")

    def __init__(self):
        self.client = openai.OpenAI(api_key=config.get_openai_key())
        self.assistant_id = self._get_or_create_assistant()

    def _get_or_create_assistant(self):
        # 1. Пытаемся прочитать ID из файла
        if self.ASSISTANT_ID_FILE.exists():
            assistant_id = self.ASSISTANT_ID_FILE.read_text().strip()
            if assistant_id:
                logger.info(f"Using existing assistant with ID: {assistant_id}")
                return assistant_id
        
        # 2. Если файла нет или он пуст - создаем нового ассистента
        logger.info("No valid assistant ID found. Creating a new assistant...")
        
        # Загружаем инструкции из файла
        instructions = load_prompt("assistant_instructions")
        
        assistant = self.client.beta.assistants.create(
            name=self.ASSISTANT_NAME,
            instructions=instructions,
            tools=[{"type": "code_interpreter"}],
            model=config.get_openai_model()
        )
        assistant_id = assistant.id
        
        # 3. Сохраняем новый ID в файл
        self.ASSISTANT_ID_FILE.write_text(assistant_id)
        logger.info(f"New assistant created and saved with ID: {assistant_id}")
        return assistant_id

    def process_file(self, file_path, progress_manager, base_progress, file_progress_span, cancellation_token_getter):
        try:
            # 1. Загрузка файла в OpenAI
            progress_manager.update_progress(base_progress, f"Загрузка файла {file_path.name} в OpenAI...")
            
            with open(file_path, "rb") as f:
                file_obj = self.client.files.create(file=f, purpose="assistants")
            
            progress_manager.update_progress(
                base_progress + int(file_progress_span * 0.05), 
                f"Файл загружен, запуск AI для {file_path.name}..."
            )

            # 2. Создание потока и запуск задачи
            thread = self.client.beta.threads.create()
            
            # Загружаем промпт из файла
            message_content = load_prompt("file_processing", filename=file_path.name)
            
            self.client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=message_content,
                attachments=[{"file_id": file_obj.id, "tools": [{"type": "code_interpreter"}]}]
            )
            run = self.client.beta.threads.runs.create(
                thread_id=thread.id,
                assistant_id=self.assistant_id # ИСПРАВЛЕНО: используем сохраненный ID
            )

            # 3. Ожидание результата с "живым" прогресс-баром и обработкой rate limit
            start_time = time.time()
            estimated_duration = 90  # Среднее предполагаемое время на файл в секундах
            max_retries = 3
            retry_count = 0

            while retry_count < max_retries:
                while run.status in ['queued', 'in_progress']:
                    if cancellation_token_getter():
                        logger.info(f"Cancellation requested for run {run.id}. Attempting to cancel on OpenAI.")
                        self.client.beta.threads.runs.cancel(thread_id=thread.id, run_id=run.id)
                        return None

                    elapsed = time.time() - start_time
                    fake_progress_pct = min((elapsed / 90) * 0.85, 0.85)
                    current_progress = base_progress + int(file_progress_span * (0.05 + fake_progress_pct))
                    
                    progress_manager.update_progress(
                        current_progress, 
                        f"AI анализирует {file_path.name} (статус: {run.status})..."
                    )

                    time.sleep(2)
                    run = self.client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)

                # Обработка завершенного run
                if run.status == 'completed':
                    progress_manager.update_progress(
                        base_progress + int(file_progress_span * 0.95),
                        f"AI завершил анализ, получение результатов для {file_path.name}..."
                    )
                    
                    # Получаем ответ
                    messages = self.client.beta.threads.messages.list(thread_id=thread.id)
                    for message in messages:
                        if message.role == 'assistant':
                            for content_block in message.content:
                                if content_block.type == 'text':
                                    json_text = content_block.text.value
                                    try:
                                        if json_text.startswith("```json"):
                                            json_text = json_text[7:-4]
                                        return json.loads(json_text)
                                    except json.JSONDecodeError as e:
                                        logger.error(f"Failed to decode JSON from AI for {file_path.name}: {e}")
                                        logger.debug(f"Received text: {json_text}")
                                        return None
                    return None  # Если ассистент не ответил

                elif run.status in ['failed', 'cancelled', 'expired']:
                    # Проверяем, если это rate limit - пытаемся повторить
                    if (run.status == 'failed' and run.last_error and 
                        run.last_error.code == 'rate_limit_exceeded' and retry_count < max_retries - 1):
                        
                        logger.warning(f"Rate limit для файла {file_path.name} (попытка {retry_count + 1}/{max_retries}): {run.last_error.message}")
                        
                        # Извлекаем время ожидания из сообщения об ошибке
                        import re
                        wait_match = re.search(r'try again in ([\d.]+)s', run.last_error.message)
                        wait_time = float(wait_match.group(1)) if wait_match else 5.0
                        
                        logger.info(f"Ожидание {wait_time} секунд перед повторной попыткой...")
                        progress_manager.update_progress(
                            base_progress + int(file_progress_span * 0.7),
                            f"Rate limit. Ожидание {wait_time:.1f}с перед попыткой {retry_count + 2}/{max_retries} для {file_path.name}..."
                        )
                        
                        # Ждем указанное время + небольшой буфер
                        time.sleep(wait_time + 1.0)
                        
                        # Проверяем отмену после ожидания
                        if cancellation_token_getter():
                            logger.info(f"Cancellation requested during rate limit wait for {file_path.name}.")
                            return None
                        
                        # Повторяем запрос
                        retry_count += 1
                        logger.info(f"Повторная попытка {retry_count + 1}/{max_retries} обработки файла {file_path.name} после rate limit.")
                        progress_manager.update_progress(
                            base_progress + int(file_progress_span * 0.1),
                            f"Повторная попытка {retry_count + 1}/{max_retries} для {file_path.name}..."
                        )
                        
                        # Создаем новый run
                        run = self.client.beta.threads.runs.create(
                            thread_id=thread.id,
                            assistant_id=self.assistant_id
                        )
                        
                        # Сбрасываем время начала для нового run
                        start_time = time.time()
                        continue  # Переходим к следующей итерации внешнего цикла
                    else:
                        logger.error(f"Run for file {file_path.name} did not complete. Status: {run.status}. Last error: {run.last_error}")
                        return None
                
                # Выходим из внешнего цикла если run завершился успешно или с неисправимой ошибкой
                break

            return None  # На случай если все попытки исчерпаны

        except Exception as e:
            logger.error(f"An error occurred in AssistantManager for {file_path.name}: {e}", exc_info=True)
            return None
        finally:
            if 'file_obj' in locals() and file_obj:
                try:
                    self.client.files.delete(file_obj.id)
                    logger.info(f"Cleaned up file {file_obj.id} from OpenAI.")
                except Exception as cleanup_error:
                    logger.error(f"Failed to clean up file {file_obj.id}: {cleanup_error}") 
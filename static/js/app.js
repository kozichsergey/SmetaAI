// Глобальные переменные
let statusInterval;

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', function() {
    // Не запускаем интервал сразу, а только после первого вызова
    refreshStatus();
    loadFiles();
    loadConfig();
    loadAILogs();
    initTabs();
    const brainMenu = document.querySelector('a[href="#brain-section"]');
    if (brainMenu) {
        brainMenu.addEventListener('click', showBrainSection);
    }
});

// Инициализация переключения вкладок
function initTabs() {
    const navLinks = document.querySelectorAll('.sidebar .nav-link');
    const contentSections = document.querySelectorAll('main > div[id$="-section"]');
    
    navLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            
            navLinks.forEach(l => l.classList.remove('active'));
            this.classList.add('active');
            
            const targetId = this.getAttribute('href').substring(1) + '-section';

            contentSections.forEach(section => {
                if (section.id === targetId) {
                    section.style.display = 'block';
                } else {
                    section.style.display = 'none';
                }
            });
            
            // Если переключились на вкладку "Файлы", обновим список
            if (targetId === 'files-section') {
                loadFiles();
            }
            // Если на "Логи", обновим логи
            if (targetId === 'logs-section') {
                loadAILogs();
            }
        });
    });
    
    // Показываем дашборд по умолчанию
    document.getElementById('dashboard-section').style.display = 'block';
}

// --- Управление состоянием ---

// Главная функция обновления статуса. Вызывается регулярно.
async function refreshStatus() {
    try {
        const response = await fetch('/api/status');
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const status = await response.json();
        
        updateDisplay(status);
        
        // Перезапускаем или останавливаем интервал в зависимости от статуса
        const isTaskActive = status.is_running || status.status === 'success' || status.status === 'error';
        
        if (isTaskActive && !statusInterval) {
            // Если задача активна и интервал не запущен, запускаем частый опрос
            statusInterval = setInterval(refreshStatus, 2000);
        } else if (!isTaskActive && statusInterval) {
            // Если задача неактивна и интервал запущен, останавливаем его
            clearInterval(statusInterval);
            statusInterval = null;
        }
        
    } catch (error) {
        console.error('Ошибка получения статуса:', error);
        // При ошибке останавливаем опрос, чтобы не спамить консоль
        if (statusInterval) {
            clearInterval(statusInterval);
            statusInterval = null;
        }
        showNotification('Ошибка подключения к серверу. Обновите страницу.', 'error');
    }
}

// Запуск задачи (любой)
async function startTask(endpoint) {
    // Проверяем, не запущена ли уже задача
    const currentStatus = await fetch('/api/status').then(res => res.json());
    if (currentStatus.is_running) {
        showNotification('Уже выполняется другая задача', 'warning');
        return;
    }

    try {
        // Сбрасываем предыдущий статус перед запуском новой задачи
        await fetch('/api/reset_status', { method: 'POST' });

        const response = await fetch(endpoint, { method: 'POST' });
        const result = await response.json();
        
        if (response.ok) {
            showNotification('Задача запущена...', 'info');
            refreshStatus(); // Сразу обновляем статус, чтобы показать прогресс
        } else {
            showNotification(result.error || 'Ошибка запуска задачи', 'error');
        }
    } catch (error) {
        console.error(`Ошибка запуска задачи ${endpoint}:`, error);
        showNotification('Ошибка подключения к серверу', 'error');
    }
}


// --- Обновление интерфейса ---

// Единая функция для обновления всего интерфейса на основе статуса
function updateDisplay(status) {
    if (!status || typeof status !== 'object') return;

    const isTaskRunning = status.is_running;
    const isTaskFinished = status.status === 'success' || status.status === 'error';

    updateProgressDisplay(status, isTaskRunning, isTaskFinished);
    updateButtonsState(status);
    updateDashboardStats(status);
    
    // Если задача завершилась, запускаем таймер на сброс
    if (isTaskFinished) {
        // Устанавливаем таймер, который сбросит прогресс через 5 секунд
        setTimeout(() => {
            // Перед сбросом еще раз проверим, что новая задача не была запущена
            fetch('/api/status').then(res => res.json()).then(currentStatus => {
                if (!currentStatus.is_running) {
                    resetProgressView();
                }
            });
        }, 5000); 
    }
}

// Обновление блока с прогрессом
function updateProgressDisplay(status, isTaskRunning, isTaskFinished) {
    const progressSection = document.getElementById('progress-section');
    const progressBar = document.getElementById('progress-bar');
    const progressMessage = document.getElementById('progress-message');
    const taskNameDisplay = document.getElementById('progress-task-name');
    
    if (isTaskRunning || isTaskFinished) {
        progressSection.style.display = 'block';

        const taskMap = {
            'ingest': 'Загрузка данных',
            'optimize': 'Оптимизация базы знаний',
            'calculate': 'Расчет сметы'
        };
        taskNameDisplay.textContent = taskMap[status.current_task] || 'Выполнение задачи...';
        
        progressBar.style.width = status.progress_percent + '%';
        progressBar.setAttribute('aria-valuenow', status.progress_percent);
        progressMessage.textContent = status.message;

        // Управление цветом и анимацией
        progressBar.classList.remove('bg-success', 'bg-danger');
        progressBar.classList.toggle('progress-bar-animated', isTaskRunning);
        
        if (status.status === 'success') {
            progressBar.classList.add('bg-success');
        } else if (status.status === 'error') {
            progressBar.classList.add('bg-danger');
        }
    } else {
        progressSection.style.display = 'none';
    }
}

// Сброс состояния прогресса (вызывается кнопкой "OK")
async function resetProgressView() {
    try {
        await fetch('/api/reset_status', { method: 'POST' });
        refreshStatus(); // Обновляем отображение
    } catch (error) {
        console.error('Ошибка сброса статуса:', error);
    }
}

// Обновление состояния кнопок
function updateButtonsState(status) {
    const isProcessing = status.is_running; // Исправлено: смотрим на is_running
    
    document.getElementById('ingest-btn').disabled = isProcessing;
    document.getElementById('optimize-btn').disabled = isProcessing;
    document.getElementById('calculate-btn').disabled = isProcessing;
    document.getElementById('clear-data-btn').disabled = isProcessing;
    
    // Управление кнопками "Обновить" и "Остановить"
    const refreshBtn = document.getElementById('refresh-btn');
    const cancelBtn = document.getElementById('cancel-btn');
    
    if (refreshBtn) {
        refreshBtn.style.display = isProcessing ? 'none' : 'inline-block';
    }
    
    if (cancelBtn) {
        cancelBtn.style.display = isProcessing ? 'inline-block' : 'none';
    }
    
    // Старая кнопка отмены (если есть) - скрываем
    const oldCancelBtn = document.getElementById('cancel-task-btn');
    if (oldCancelBtn) {
        oldCancelBtn.style.display = 'none';
    }
}

// Обновление статистики на дашборде
function updateDashboardStats(status) {
    document.getElementById('input-files-count').textContent = status.input_files_count || 0;
    document.getElementById('raw-data-count').textContent = status.raw_data_size || 0;
    document.getElementById('processed-files-count').textContent = status.processed_files_count || 0;
    document.getElementById('brain-count').textContent = status.brain_size || 0;
}

// Подтверждение и запуск очистки данных
function confirmClearData() {
    if (confirm("Вы уверены, что хотите полностью удалить raw_data.json и brain.json? Это действие необратимо.")) {
        clearData();
    }
}

async function clearData() {
    try {
        const response = await fetch('/api/clear_data', { method: 'POST' });
        const result = await response.json();
        if (response.ok) {
            showNotification(result.message, 'success');
            refreshStatus(); // Обновляем дашборд
            loadFiles(); // Обновляем списки файлов (хотя они не должны измениться)
        } else {
            showNotification(result.error || 'Ошибка при очистке', 'error');
        }
    } catch (error) {
        console.error('Ошибка при очистке данных:', error);
        showNotification('Ошибка подключения к серверу', 'error');
    }
}


// --- Загрузка данных (файлы, конфиг, логи) ---

function loadFiles() {
    console.log("Загрузка списков файлов...");
    const inputList = document.getElementById('input-files-list');
    const calculateList = document.getElementById('calculate-files-list');
    const outputList = document.getElementById('output-files-list');

    inputList.innerHTML = '<li><i class="fas fa-spinner fa-spin"></i> Загрузка...</li>';
    calculateList.innerHTML = '<li><i class="fas fa-spinner fa-spin"></i> Загрузка...</li>';
    outputList.innerHTML = '<li><i class="fas fa-spinner fa-spin"></i> Загрузка...</li>';

    fetch('/api/files')
        .then(response => response.json())
        .then(data => {
            // Файлы для обучения
            inputList.innerHTML = '';
            if (data.input_files && data.input_files.length > 0) {
                data.input_files.forEach(file => {
                    const li = document.createElement('li');
                    li.textContent = file;
                    li.className = 'list-group-item';
                    inputList.appendChild(li);
                });
            } else {
                inputList.innerHTML = '<li class="list-group-item text-muted">Папка пуста</li>';
            }

            // Файлы для расчета
            calculateList.innerHTML = '';
            if (data.calculate_files && data.calculate_files.length > 0) {
                data.calculate_files.forEach(file => {
                    const li = document.createElement('li');
                    li.textContent = file;
                    li.className = 'list-group-item';
                    calculateList.appendChild(li);
                });
            } else {
                calculateList.innerHTML = '<li class="list-group-item text-muted">Папка пуста</li>';
            }

            // Готовые файлы
            outputList.innerHTML = '';
            if (data.output_files && data.output_files.length > 0) {
                data.output_files.forEach(file => {
                    const li = document.createElement('li');
                    li.textContent = file;
                    li.className = 'list-group-item';
                    outputList.appendChild(li);
                });
            } else {
                outputList.innerHTML = '<li class="list-group-item text-muted">Папка пуста</li>';
            }
        })
        .catch(error => {
            console.error('Ошибка при загрузке файлов:', error);
            inputList.innerHTML = '<li class="list-group-item text-danger">Ошибка загрузки</li>';
            calculateList.innerHTML = '<li class="list-group-item text-danger">Ошибка загрузки</li>';
            outputList.innerHTML = '<li class="list-group-item text-danger">Ошибка загрузки</li>';
        });
}

// Загрузка конфигурации
async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        const config = await response.json();
        
        document.getElementById('openai-key').value = config.openai_api_key;
        document.getElementById('openai-model').value = config.openai_model || 'o4-mini-2025-04-16';
        
        // Показываем или скрываем предупреждение об API ключе
        const apiKeyWarning = document.getElementById('api-key-warning');
        if (!config.openai_api_key) {
            apiKeyWarning.style.display = 'block';
        } else {
            apiKeyWarning.style.display = 'none';
        }
        
        updateAIStatus(!!config.openai_api_key); // Статус зависит только от наличия ключа
    } catch (error) {
        console.error('Ошибка загрузки конфигурации:', error);
    }
}

// Сохранение конфигурации
async function saveConfig() {
    try {
        const apiKey = document.getElementById('openai-key').value;
        const model = document.getElementById('openai-model').value;
        
        const response = await fetch('/api/config', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                openai_api_key: apiKey,
                openai_model: model
            })
        });
        
        const result = await response.json();
        
        if (response.ok) {
            showNotification('Настройки сохранены', 'success');
            // Обновляем статус после сохранения
            loadConfig(); 
        } else {
            showNotification(result.error || 'Ошибка сохранения', 'error');
        }
        
    } catch (error) {
        console.error('Ошибка сохранения конфигурации:', error);
        showNotification('Ошибка подключения к серверу', 'error');
    }
}

// Обновление статуса AI
function updateAIStatus(enabled) {
    const statusElement = document.getElementById('ai-status');
    if (enabled) {
        statusElement.textContent = 'Включена';
        statusElement.className = 'text-success';
        } else {
        statusElement.textContent = 'Отключена';
        statusElement.className = 'text-muted';
    }
}

// Загрузка логов AI-оптимизации
async function loadAILogs() {
    try {
        const response = await fetch('/api/ai_logs');
        const data = await response.json();
        
        const logsList = document.getElementById('ai-logs-list');
        const statsDiv = document.getElementById('ai-stats');
        
        if (data && data.entries && data.entries.length > 0) {
            // Отображаем историю логов
            let logsHtml = '<ul class="list-group">';
            data.entries.slice(-10).reverse().forEach(entry => {
                const timestamp = new Date(entry.timestamp).toLocaleString('ru-RU');
                const statusClass = entry.status === 'success' ? 'text-success' : 
                                  entry.status === 'error' ? 'text-danger' : 'text-info';
                const statusIcon = entry.status === 'success' ? 'fas fa-check' :
                                 entry.status === 'error' ? 'fas fa-times' : 'fas fa-info';
                
                logsHtml += `
                    <li class="list-group-item">
                        <i class="${statusIcon} ${statusClass}"></i>
                        <strong>${timestamp}</strong><br>
                        <small class="text-muted">${entry.message}</small>
                    </li>
        `;
    });
            logsHtml += '</ul>';
            logsList.innerHTML = logsHtml;
            
            // Отображаем статистику последней оптимизации
            const lastEntry = data.entries[data.entries.length - 1];
            if (lastEntry && lastEntry.status === 'success') {
                statsDiv.innerHTML = `
                    <div class="alert alert-success">
                        <i class="fas fa-check"></i>
                        <strong>Последняя оптимизация:</strong><br>
                        <small>${new Date(lastEntry.timestamp).toLocaleString('ru-RU')}</small>
                    </div>
                `;
            } else {
                statsDiv.innerHTML = '<p class="text-muted">Нет данных о последней оптимизации</p>';
            }
        } else {
            logsList.innerHTML = '<p class="text-muted">История логов пуста</p>';
            statsDiv.innerHTML = '<p class="text-muted">Нет данных</p>';
        }
        
    } catch (error) {
        console.error('Ошибка загрузки логов:', error);
        document.getElementById('ai-logs-list').innerHTML = '<p class="text-danger">Ошибка загрузки логов</p>';
    }
}

// Обработка необработанных промисов
window.addEventListener('unhandledrejection', function(e) {
    console.error('Необработанная ошибка промиса:', e.reason);
    showNotification('Ошибка выполнения операции', 'error');
}); 

// Показать уведомление
function showNotification(message, type = 'info') {
    // Создаем уведомление
    const notification = document.createElement('div');
    notification.className = `alert alert-${type === 'error' ? 'danger' : type} alert-dismissible fade show position-fixed`;
    notification.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
    
    notification.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    document.body.appendChild(notification);
    
    // Автоматически удаляем через 5 секунд
    setTimeout(() => {
        if (notification.parentNode) {
            notification.remove();
        }
    }, 5000);
}

// Обработка ошибок
window.addEventListener('error', function(e) {
    console.error('JavaScript ошибка:', e.error);
    showNotification('Произошла ошибка в интерфейсе', 'error');
});

// Глобальные переменные для модального окна
let selectedFile = null;
let calculateModal = null;

// Показать модальное окно для выбора файла
function showCalculateModal() {
    if (!calculateModal) {
        calculateModal = new bootstrap.Modal(document.getElementById('calculateModal'));
    }
    
    // Загружаем список файлов
    loadFileSelectionList();
    calculateModal.show();
}

// Загрузить список файлов для выбора
async function loadFileSelectionList() {
    try {
        const response = await fetch('/api/files');
        const files = await response.json();
        
        const fileList = document.getElementById('file-selection-list');
        const startBtn = document.getElementById('start-calculate-btn');
        
        if (!files.input_files || files.input_files.length === 0) {
            fileList.innerHTML = '<p class="text-muted">Файлы не найдены</p>';
            return;
        }
        
        let html = '<div class="list-group">';
        
        files.input_files.forEach(file => {
            const size = formatFileSize(file.size);
            const date = new Date(file.modified).toLocaleDateString('ru-RU');
            
            html += `
                <button type="button" class="list-group-item list-group-item-action file-select-item" 
                        data-filename="${file.name}" onclick="selectFile('${file.name}')">
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <h6 class="mb-1">${file.name}</h6>
                            <small class="text-muted">
                                <i class="fas fa-calendar"></i> ${date} | 
                                <i class="fas fa-weight-hanging"></i> ${size}
                            </small>
                        </div>
                        <div class="file-select-indicator">
                            <i class="fas fa-circle text-muted"></i>
                        </div>
                    </div>
                </button>
            `;
        });
        
        html += '</div>';
        fileList.innerHTML = html;
        
        // Сбрасываем выбор
        selectedFile = null;
        startBtn.disabled = true;
        
    } catch (error) {
        console.error('Ошибка загрузки файлов:', error);
        showNotification('Ошибка загрузки списка файлов', 'error');
    }
}

// Выбрать файл
function selectFile(filename) {
    selectedFile = filename;
    
    // Обновляем индикаторы
    document.querySelectorAll('.file-select-item').forEach(item => {
        item.classList.remove('active');
        const indicator = item.querySelector('.file-select-indicator i');
        indicator.className = 'fas fa-circle text-muted';
    });
    
    // Выделяем выбранный файл
    const selectedItem = document.querySelector(`[data-filename="${filename}"]`);
    if (selectedItem) {
        selectedItem.classList.add('active');
        const indicator = selectedItem.querySelector('.file-select-indicator i');
        indicator.className = 'fas fa-check-circle text-success';
    }
    
    // Активируем кнопку
    document.getElementById('start-calculate-btn').disabled = false;
}

// Запустить расчет сметы
async function startCalculate() {
    if (isProcessing) {
        showNotification('Уже выполняется другая задача', 'warning');
        return;
    }
    
    try {
        const response = await fetch('/api/calculate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
            // Тело запроса больше не нужно, бэкенд обработает все файлы
        });
        
        const result = await response.json();
        
        if (response.ok) {
            showNotification(`Расчет всех файлов запущен`, 'success');
            showProgressSection();
        } else {
            showNotification(result.error || 'Ошибка запуска расчета', 'error');
        }
        
    } catch (error) {
        console.error('Ошибка запуска расчета:', error);
        showNotification('Ошибка подключения к серверу', 'error');
    }
    startStatusPolling();
}

// Форматирование размера файла
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Б';
    
    const k = 1024;
    const sizes = ['Б', 'КБ', 'МБ', 'ГБ'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

// Показать секцию прогресса
function showProgressSection() {
    const progressSection = document.getElementById('progress-section');
    progressSection.style.display = 'block';
    progressSection.classList.add('fade-in');
}

// Скрыть секцию прогресса
function hideProgressSection() {
    const progressSection = document.getElementById('progress-section');
    progressSection.style.display = 'none';
}

// Обновление прогресса
function updateProgress(progress, message) {
        const progressBar = document.getElementById('progress-bar');
        const progressMessage = document.getElementById('progress-message');
        
    progressBar.style.width = progress + '%';
    progressBar.setAttribute('aria-valuenow', progress);
    progressMessage.textContent = message;
}

// Форматирование информации о вариантах цен
function formatPriceVariants(item) {
    const analysis = item.price_analysis;
    if (!analysis) {
        return '<span class="text-muted">-</span>';
    }
    
    let html = '';
    let hasWarnings = false;
    
    // Анализ цен материала
    if (analysis.material && analysis.material.original_prices && analysis.material.original_prices.length > 0) {
        const materialCount = analysis.material.original_prices.length;
        const materialVariance = analysis.material.variance_percent || 0;
        
        html += `<div class="small">
            <span class="badge bg-secondary">М: ${materialCount}</span>`;
        
        if (materialVariance > 0) {
            html += ` <span class="text-muted">(±${materialVariance}%)</span>`;
        }
        
        // Показываем предупреждение только если цена не одобрена
        if (shouldShowWarning(analysis.material, item.material_price_approved)) {
            hasWarnings = true;
        }
        
        html += '</div>';
    }
    
    // Анализ цен работы
    if (analysis.work && analysis.work.original_prices && analysis.work.original_prices.length > 0) {
        const workCount = analysis.work.original_prices.length;
        const workVariance = analysis.work.variance_percent || 0;
        
        html += `<div class="small">
            <span class="badge bg-info">Р: ${workCount}</span>`;
        
        if (workVariance > 0) {
            html += ` <span class="text-muted">(±${workVariance}%)</span>`;
        }
        
        // Показываем предупреждение только если цена не одобрена
        if (shouldShowWarning(analysis.work, item.work_price_approved)) {
            hasWarnings = true;
        }
        
        html += '</div>';
    }
    
    // Одна общая иконка предупреждения если есть неодобренные проблемы
    if (hasWarnings) {
        html += `<div class="small text-warning mt-1">
            <i class="fas fa-exclamation-triangle"></i> Требует проверки
        </div>`;
    }
    
    return html || '<span class="text-muted">-</span>';
}

// Загрузка данных полной базы
async function loadRawData() {
    try {
        const response = await fetch('/api/raw_data');
        const data = await response.json();
        
        const tbody = document.querySelector('#rawTable tbody');
        const fileFilter = document.getElementById('rawFileFilter');
        
        // Проверяем существование элементов
        if (!tbody || !fileFilter) {
            console.warn('Элементы таблицы полной базы не найдены');
            return;
        }
        
        tbody.innerHTML = '';
        
        // Очищаем и заполняем фильтр файлов
        fileFilter.innerHTML = '<option value="">Все файлы</option>';
        const uniqueFiles = new Set();
        
        // Сохраняем данные для редактирования
        currentRawData = data.records || [];
        
        if (currentRawData.length > 0) {
            currentRawData.forEach((record, index) => {
                const row = document.createElement('tr');
                
                // Форматируем цены
                const materialPrice = record.material_price || 0;
                const workPrice = record.work_price || 0;
                const sourceFile = record.source_file || '';
                
                // Добавляем файл в фильтр
                if (sourceFile) {
                    uniqueFiles.add(sourceFile);
                }
                
                row.innerHTML = `
                    <td>${record.name || ''}</td>
                    <td>${record.unit || ''}</td>
                    <td>${materialPrice.toFixed(2)}</td>
                    <td>${workPrice.toFixed(2)}</td>
                    <td><small>${sourceFile}</small></td>
                    <td>
                        <button class="btn btn-sm btn-outline-primary" onclick="editRawItem(${index})">
                            <i class="fas fa-edit"></i>
                        </button>
                    </td>
                `;
                
                tbody.appendChild(row);
            });
            
            // Заполняем фильтр файлов
            Array.from(uniqueFiles).sort().forEach(file => {
                const option = document.createElement('option');
                option.value = file;
                option.textContent = file.split('/').pop(); // Показываем только имя файла
                fileFilter.appendChild(option);
            });
            
            // Обновляем счетчик
            document.getElementById('rawTableCounter').textContent = `Показано: ${currentRawData.length} записей`;
            
        } else {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">Нет данных. Загрузите файлы для обработки.</td></tr>';
            document.getElementById('rawTableCounter').textContent = 'Показано: 0 записей';
        }

    } catch (error) {
        console.error('Ошибка загрузки полной базы:', error);
        showNotification('Ошибка загрузки полной базы данных', 'danger');
    }
}

// --- Загрузка и отображение базы знаний ---
function showBrainSection() {
    hideAllSections();
    document.getElementById('brain-section').style.display = 'block';
    loadRawData();
    loadBrainData();
}

// Загрузка данных базы знаний
async function loadBrainData() {
    try {
        const response = await fetch('/api/brain');
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const brainData = await response.json();
        
        // Сохраняем данные для редактирования
        currentBrainData = Array.isArray(brainData) ? brainData : [];
        
        const tbody = document.querySelector('#brainTable tbody');
        
        // Проверяем существование элемента
        if (!tbody) {
            console.warn('Элемент таблицы базы знаний не найден');
            return;
        }
        
        tbody.innerHTML = '';
        
        if (currentBrainData.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">База знаний пуста. Запустите оптимизацию.</td></tr>';
            const counter = document.getElementById('brainTableCounter');
            if (counter) counter.textContent = 'Показано: 0 записей';
            return;
        }
        
        currentBrainData.forEach((item, index) => {
            const row = document.createElement('tr');
            
            // Форматируем источники
            const sources = Array.isArray(item.source_files) ? 
                item.source_files.map(f => f.split('/').pop()).join(', ') : 
                (item.source_files || '');
            
            // Форматируем цены
            const materialPrice = item.material_price > 0 ? 
                `${item.material_price.toLocaleString()} руб.` : '-';
            const workPrice = item.work_price > 0 ? 
                `${item.work_price.toLocaleString()} руб.` : '-';
            
            // Форматируем информацию о вариантах цен
            const priceVariants = formatPriceVariants(item);
            
            row.innerHTML = `
                <td>${item.name || ''}</td>
                <td>${item.unit || ''}</td>
                <td>${materialPrice}</td>
                <td>${workPrice}</td>
                <td>${priceVariants}</td>
                <td>${item.cluster_size || 1}</td>
                <td><small>${sources}</small></td>
                <td>
                    <button class="btn btn-sm btn-outline-primary" onclick="editBrainItem(${index})">
                        <i class="fas fa-edit"></i>
                    </button>
                </td>
            `;
            
            tbody.appendChild(row);
        });
        
        // Устанавливаем начальный счетчик
        const counter = document.getElementById('brainTableCounter');
        if (counter) counter.textContent = `Показано: ${currentBrainData.length} записей`;
        
    } catch (error) {
        console.error('Ошибка загрузки базы знаний:', error);
        
        // Инициализируем пустую базу при ошибке
        currentBrainData = [];
        const tbody = document.querySelector('#brainTable tbody');
        if (tbody) {
            tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted">База знаний пуста. Запустите оптимизацию.</td></tr>';
        }
        const counter = document.getElementById('brainTableCounter');
        if (counter) counter.textContent = 'Показано: 0 записей';
        
        // Показываем ошибку только если это не просто отсутствие файла
        if (!error.message.includes('404')) {
            showNotification('Ошибка загрузки базы знаний', 'danger');
        }
    }
}

function exportBrain() {
    window.location.href = '/api/brain/export';
}

function importBrain(event) {
    const file = event.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    fetch('/api/brain/import', {
            method: 'POST',
        body: formData
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            showNotification('Импорт завершен', 'success');
            loadBrainData();
        } else {
            showNotification(data.error || 'Ошибка импорта', 'error');
        }
    });
}

function hideAllSections() {
    document.getElementById('dashboard-section').style.display = 'none';
    document.getElementById('files-section').style.display = 'none';
    document.getElementById('logs-section').style.display = 'none';
    document.getElementById('brain-section').style.display = 'none';
    document.getElementById('settings-section').style.display = 'none';
}

// Обработка меню
// document.querySelector('a[href="#brain-section"]').addEventListener('click', showBrainSection); // This line is removed as per the edit hint

// Автоматическая загрузка данных при переключении на вкладки
document.addEventListener('DOMContentLoaded', function() {
    // Обработчик для вкладки "База знаний"
    const knowledgeTab = document.getElementById('knowledge-tab');
    if (knowledgeTab) {
        knowledgeTab.addEventListener('shown.bs.tab', function() {
            loadBrainData();
        });
    }
    
    // Обработчик для вкладки "Полная база"
    const rawTab = document.getElementById('raw-tab');
    if (rawTab) {
        rawTab.addEventListener('shown.bs.tab', function() {
            loadRawData();
        });
    }
});

function cancelTask() {
    fetch('/api/cancel_task', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showNotification('Задача отменена', 'info');
                // Обновляем статус, чтобы убрать прогресс бар и активировать кнопки
                refreshStatus();
            } else {
                showNotification(data.error || 'Не удалось отменить задачу', 'danger');
            }
        })
        .catch(() => showNotification('Ошибка при отмене задачи', 'danger'));
}

// Новая функция для кнопки "Остановить"
function cancelCurrentTask() {
    if (confirm('Вы уверены, что хотите остановить выполнение текущей задачи?')) {
        fetch('/api/cancel_task', { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showNotification('Задача остановлена', 'info');
                    // Обновляем статус, чтобы убрать прогресс бар и активировать кнопки
                    refreshStatus();
    } else {
                    showNotification(data.error || 'Не удалось остановить задачу', 'danger');
                }
            })
            .catch(() => showNotification('Ошибка при остановке задачи', 'danger'));
    }
}

// Заглушка для редактирования записи
function editBrainItem(index) {
    showNotification('Функция редактирования в разработке', 'info');
}

// Глобальная переменная для хранения данных базы знаний
let currentBrainData = [];
// Глобальная переменная для хранения данных полной базы
let currentRawData = [];

// Редактирование записи базы знаний
async function editBrainItem(index) {
    if (!currentBrainData[index]) {
        showNotification('Запись не найдена', 'danger');
        return;
    }
    
    const item = currentBrainData[index];
    
    // Заполняем основные поля
    document.getElementById('editBrainName').value = item.name || '';
    document.getElementById('editBrainUnit').value = item.unit || '';
    document.getElementById('editBrainMaterialPrice').value = item.material_price || 0;
    document.getElementById('editBrainWorkPrice').value = item.work_price || 0;
    document.getElementById('editBrainIndex').value = index;
    
    // Заполняем чекбоксы одобрения
    document.getElementById('editBrainMaterialApproved').checked = item.material_price_approved || false;
    document.getElementById('editBrainWorkApproved').checked = item.work_price_approved || false;
    
    // Отображаем источники
    const sources = Array.isArray(item.source_files) ? 
        item.source_files.map(f => f.split('/').pop()).join(', ') : 
        (item.source_files || 'Нет данных');
    document.getElementById('editBrainSources').textContent = sources;
    
    // Отображаем анализ цен
    displayPriceAnalysis(item);
    
    // Показываем модальное окно
    const modal = new bootstrap.Modal(document.getElementById('editBrainModal'));
    modal.show();
}

// Отображение детального анализа цен
function displayPriceAnalysis(item) {
    const analysisSection = document.getElementById('priceAnalysisSection');
    const materialAnalysis = document.getElementById('materialPriceAnalysis');
    const workAnalysis = document.getElementById('workPriceAnalysis');
    
    let hasAnalysis = false;
    
    // Анализ цен материала
    if (item.price_analysis && item.price_analysis.material && item.price_analysis.material.original_prices) {
        const material = item.price_analysis.material;
        hasAnalysis = true;
        
        materialAnalysis.style.display = 'block';
        
        // Список цен
        const pricesList = document.getElementById('materialPricesList');
        let pricesHtml = '';
        
        material.original_prices.forEach((price, i) => {
            const isUsed = material.used_prices ? material.used_prices.includes(price) : true;
            const isExcluded = material.excluded_prices ? material.excluded_prices.includes(price) : false;
            
            let badgeClass = 'bg-secondary';
            let tooltip = 'Использована в расчете';
            
            if (isExcluded) {
                badgeClass = 'bg-danger';
                tooltip = 'Исключена как крайнее значение';
            } else if (!isUsed) {
                badgeClass = 'bg-warning';
                tooltip = 'Не использована в расчете';
            }
            
            pricesHtml += `
                <span class="badge ${badgeClass} me-1 position-relative" title="${tooltip}">
                    ${price.toLocaleString()} руб.
                    <button type="button" class="btn-close btn-close-white position-absolute top-0 start-100 translate-middle" 
                            style="font-size: 0.5em; width: 12px; height: 12px;"
                            onclick="removePriceFromAnalysis('material', ${i})"
                            title="Удалить эту цену"></button>
                </span>`;
        });
        
        pricesList.innerHTML = pricesHtml;
        
        // Статистика
        const stats = document.getElementById('materialPriceStats');
        let statsHtml = `<strong>Метод:</strong> ${getCalculationMethodText(material.calculation_method)}<br>`;
        statsHtml += `<strong>Разброс:</strong> ±${material.variance_percent || 0}%<br>`;
        
        if (material.warning) {
            statsHtml += `<strong class="text-warning">⚠️ ${material.warning}</strong>`;
        }
        
        stats.innerHTML = statsHtml;
        
            } else {
        materialAnalysis.style.display = 'none';
    }
    
    // Анализ цен работы
    if (item.price_analysis && item.price_analysis.work && item.price_analysis.work.original_prices) {
        const work = item.price_analysis.work;
        hasAnalysis = true;
        
        workAnalysis.style.display = 'block';
        
        // Список цен
        const pricesList = document.getElementById('workPricesList');
        let pricesHtml = '';
        
        work.original_prices.forEach((price, i) => {
            const isUsed = work.used_prices ? work.used_prices.includes(price) : true;
            const isExcluded = work.excluded_prices ? work.excluded_prices.includes(price) : false;
            
            let badgeClass = 'bg-info';
            let tooltip = 'Использована в расчете';
            
            if (isExcluded) {
                badgeClass = 'bg-danger';
                tooltip = 'Исключена как крайнее значение';
            } else if (!isUsed) {
                badgeClass = 'bg-warning';
                tooltip = 'Не использована в расчете';
            }
            
            pricesHtml += `
                <span class="badge ${badgeClass} me-1 position-relative" title="${tooltip}">
                    ${price.toLocaleString()} руб.
                    <button type="button" class="btn-close btn-close-white position-absolute top-0 start-100 translate-middle" 
                            style="font-size: 0.5em; width: 12px; height: 12px;"
                            onclick="removePriceFromAnalysis('work', ${i})"
                            title="Удалить эту цену"></button>
                </span>`;
        });
        
        pricesList.innerHTML = pricesHtml;
        
        // Статистика
        const stats = document.getElementById('workPriceStats');
        let statsHtml = `<strong>Метод:</strong> ${getCalculationMethodText(work.calculation_method)}<br>`;
        statsHtml += `<strong>Разброс:</strong> ±${work.variance_percent || 0}%<br>`;
        
        if (work.warning) {
            statsHtml += `<strong class="text-warning">⚠️ ${work.warning}</strong>`;
        }
        
        stats.innerHTML = statsHtml;
        
    } else {
        workAnalysis.style.display = 'none';
    }
    
    // Показываем/скрываем секцию анализа
    analysisSection.style.display = hasAnalysis ? 'block' : 'none';
}

// Получение текстового описания метода расчета
function getCalculationMethodText(method) {
    const methods = {
        'single_price': 'Одна цена',
        'average_2_prices': 'Среднее из 2 цен',
        'average_3_prices': 'Среднее из 3 цен',
        'trimmed_average_4_prices': 'Среднее из 4 цен (без крайних)',
        'trimmed_average_5_prices': 'Среднее из 5 цен (без крайних)',
        'no_prices': 'Нет цен'
    };
    
    if (method && method.startsWith('trimmed_average_')) {
        const count = method.split('_')[2];
        return `Среднее из ${count} цен (без крайних)`;
    }
    
    return methods[method] || method;
}

// Удаление отдельной цены из анализа
function removePriceFromAnalysis(priceType, priceIndex) {
    const itemIndex = parseInt(document.getElementById('editBrainIndex').value);
    const item = currentBrainData[itemIndex];
    
    if (!item || !item.price_analysis || !item.price_analysis[priceType]) {
        return;
    }
    
    const analysis = item.price_analysis[priceType];
    if (analysis.original_prices && analysis.original_prices.length > priceIndex) {
        // Удаляем цену из массива
        analysis.original_prices.splice(priceIndex, 1);
        
        // Пересчитываем итоговую цену если остались цены
        if (analysis.original_prices.length > 0) {
            // Простое среднее арифметическое для упрощения
            const newPrice = analysis.original_prices.reduce((sum, price) => sum + price, 0) / analysis.original_prices.length;
            analysis.final_price = Math.round(newPrice * 100) / 100;
            analysis.used_prices = analysis.original_prices;
            analysis.calculation_method = `manual_average_${analysis.original_prices.length}_prices`;
            analysis.warning = null; // Убираем предупреждение после ручного вмешательства
            analysis.variance_percent = 0;
            delete analysis.excluded_prices;
            
            // Обновляем итоговую цену в записи
            if (priceType === 'material') {
                item.material_price = analysis.final_price;
                document.getElementById('editBrainMaterialPrice').value = analysis.final_price;
            } else {
                item.work_price = analysis.final_price;
                document.getElementById('editBrainWorkPrice').value = analysis.final_price;
            }
        } else {
            // Если цен не осталось, обнуляем
            analysis.final_price = 0;
            if (priceType === 'material') {
                item.material_price = 0;
                document.getElementById('editBrainMaterialPrice').value = 0;
            } else {
                item.work_price = 0;
                document.getElementById('editBrainWorkPrice').value = 0;
            }
        }
        
        // Перерисовываем анализ цен
        displayPriceAnalysis(item);
    }
}

// Удаление всей записи из базы знаний
async function deleteBrainItem() {
    const itemIndex = parseInt(document.getElementById('editBrainIndex').value);
    const item = currentBrainData[itemIndex];
    
    if (!item) {
        showNotification('Запись не найдена', 'danger');
        return;
    }
    
    if (!confirm(`Вы уверены, что хотите удалить запись "${item.name}"?\n\nЭто действие нельзя отменить.`)) {
        return;
    }
    
    try {
        const response = await fetch('/api/brain/delete', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ index: itemIndex })
        });
        
        if (response.ok) {
            showNotification('Запись успешно удалена', 'success');
            
            // Закрываем модальное окно
            const modal = bootstrap.Modal.getInstance(document.getElementById('editBrainModal'));
            modal.hide();
            
            // Перезагружаем данные
            await loadBrainData();
            } else {
            const error = await response.json();
            showNotification(error.error || 'Ошибка при удалении записи', 'danger');
        }
    } catch (error) {
        console.error('Ошибка при удалении записи:', error);
        showNotification('Ошибка при удалении записи', 'danger');
    }
}

// Обновление отображения предупреждений с учетом одобрения
function shouldShowWarning(analysis, approved) {
    return analysis && analysis.warning && !approved;
}

// Сохранение изменений записи
async function saveBrainEdit() {
    const data = {
        index: parseInt(document.getElementById('editBrainIndex').value),
        name: document.getElementById('editBrainName').value,
        unit: document.getElementById('editBrainUnit').value,
        material_price: parseFloat(document.getElementById('editBrainMaterialPrice').value) || 0,
        work_price: parseFloat(document.getElementById('editBrainWorkPrice').value) || 0,
        material_price_approved: document.getElementById('editBrainMaterialApproved').checked,
        work_price_approved: document.getElementById('editBrainWorkApproved').checked
    };
    
    if (!data.name) {
        showNotification('Наименование обязательно для заполнения', 'danger');
        return;
    }
    
    try {
        const response = await fetch('/api/brain/edit', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data)
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification('Запись успешно обновлена', 'success');
            
            // Закрываем модальное окно
            const modal = bootstrap.Modal.getInstance(document.getElementById('editBrainModal'));
            modal.hide();
            
            // Перезагружаем таблицу
            loadBrainData();
        } else {
            showNotification(result.error || 'Ошибка сохранения', 'danger');
        }
        
    } catch (error) {
        console.error('Ошибка сохранения:', error);
        showNotification('Ошибка сохранения записи', 'danger');
    }
}

// Фильтрация таблицы базы знаний
function filterBrainTable() {
    const searchTerm = document.getElementById('brainSearchInput').value.toLowerCase();
    const priceFilter = document.getElementById('brainPriceFilter').value;
    
    const table = document.getElementById('brainTable');
    const rows = table.getElementsByTagName('tbody')[0].getElementsByTagName('tr');
    let visibleCount = 0;
    
    for (let i = 0; i < rows.length; i++) {
        const row = rows[i];
        const cells = row.getElementsByTagName('td');
        
        if (cells.length === 0) continue; // Пропускаем заголовки
        
        // Используем исходные данные вместо парсинга текста
        const item = currentBrainData[i];
        if (!item) continue;
        
        const name = item.name.toLowerCase();
        const materialPrice = item.material_price || 0;
        const workPrice = item.work_price || 0;
        
        // Проверка поиска
        const matchesSearch = name.includes(searchTerm);
        
        // Проверка фильтра цен
        let matchesPrice = true;
        if (priceFilter === 'material') {
            matchesPrice = materialPrice > 0;
        } else if (priceFilter === 'work') {
            matchesPrice = workPrice > 0;
        }
        
        // Показываем/скрываем строку
        if (matchesSearch && matchesPrice) {
            row.style.display = '';
            visibleCount++;
        } else {
            row.style.display = 'none';
        }
    }
    
    // Обновляем счетчик
    document.getElementById('brainTableCounter').textContent = `Показано: ${visibleCount} записей`;
}

// Фильтрация таблицы полной базы
function filterRawTable() {
    const searchTerm = document.getElementById('rawSearchInput').value.toLowerCase();
    const priceFilter = document.getElementById('rawPriceFilter').value;
    const fileFilter = document.getElementById('rawFileFilter').value;
    
    const table = document.getElementById('rawTable');
    const rows = table.getElementsByTagName('tbody')[0].getElementsByTagName('tr');
    let visibleCount = 0;
    
    for (let i = 0; i < rows.length; i++) {
        const row = rows[i];
        const cells = row.getElementsByTagName('td');
        
        if (cells.length === 0) continue; // Пропускаем заголовки
        
        // Используем исходные данные вместо парсинга текста
        const item = currentRawData[i];
        if (!item) continue;
        
        const name = item.name.toLowerCase();
        const materialPrice = item.material_price || 0;
        const workPrice = item.work_price || 0;
        const sourceFile = item.source_file || '';
        
        // Проверка поиска
        const matchesSearch = name.includes(searchTerm);
        
        // Проверка фильтра цен
        let matchesPrice = true;
        if (priceFilter === 'material') {
            matchesPrice = materialPrice > 0;
        } else if (priceFilter === 'work') {
            matchesPrice = workPrice > 0;
        }
        
        // Проверка фильтра файлов
        const matchesFile = !fileFilter || sourceFile.includes(fileFilter);
        
        // Показываем/скрываем строку
        if (matchesSearch && matchesPrice && matchesFile) {
            row.style.display = '';
            visibleCount++;
        } else {
            row.style.display = 'none';
        }
    }
    
    // Обновляем счетчик
    document.getElementById('rawTableCounter').textContent = `Показано: ${visibleCount} записей`;
}

// Редактирование записи полной базы
async function editRawItem(index) {
    if (!currentRawData[index]) {
        showNotification('Запись не найдена', 'danger');
        return;
    }
    
    const item = currentRawData[index];
    
    // Заполняем форму
    document.getElementById('editRawName').value = item.name || '';
    document.getElementById('editRawUnit').value = item.unit || '';
    document.getElementById('editRawMaterialPrice').value = item.material_price || 0;
    document.getElementById('editRawWorkPrice').value = item.work_price || 0;
    document.getElementById('editRawIndex').value = index;
    
    // Отображаем источник
    const sourceFile = item.source_file || 'Нет данных';
    document.getElementById('editRawSource').textContent = sourceFile.split('/').pop();
    
    // Показываем модальное окно
    const modal = new bootstrap.Modal(document.getElementById('editRawModal'));
    modal.show();
}

// Сохранение изменений записи полной базы
async function saveRawEdit() {
    const index = parseInt(document.getElementById('editRawIndex').value);
    const name = document.getElementById('editRawName').value.trim();
    const unit = document.getElementById('editRawUnit').value.trim();
    const materialPrice = parseFloat(document.getElementById('editRawMaterialPrice').value) || 0;
    const workPrice = parseFloat(document.getElementById('editRawWorkPrice').value) || 0;
    
    if (!name) {
        showNotification('Наименование обязательно для заполнения', 'danger');
        return;
    }
    
    if (materialPrice === 0 && workPrice === 0) {
        showNotification('Должна быть указана хотя бы одна цена', 'danger');
        return;
    }
    
    try {
        const response = await fetch('/api/raw_data/edit', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                index: index,
                name: name,
                unit: unit,
                material_price: materialPrice,
                work_price: workPrice
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification('Запись успешно обновлена', 'success');
            
            // Закрываем модальное окно
            const modal = bootstrap.Modal.getInstance(document.getElementById('editRawModal'));
            modal.hide();
            
            // Перезагружаем таблицу
            loadRawData();
        } else {
            showNotification(result.error || 'Ошибка сохранения', 'danger');
        }
        
    } catch (error) {
        console.error('Ошибка сохранения:', error);
        showNotification('Ошибка сохранения записи', 'danger');
    }
} 
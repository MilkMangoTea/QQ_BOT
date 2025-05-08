// 全局变量
let currentMemoryId = null;
let memoryData = {};
let promptOptions = [];
let llmOptions = {};
let isDarkMode = false;

// DOM 加载完成后执行
document.addEventListener('DOMContentLoaded', function() {
    // 初始化界面
    updateStatus();
    loadConfig();
    loadMemories();
    initScrollAnimation();
    initThemeToggle();

    // 每10秒更新一次状态
    setInterval(updateStatus, 10000);

    // 绑定事件
    document.getElementById('start-bot').addEventListener('click', startBot);
    document.getElementById('stop-bot').addEventListener('click', stopBot);
    document.getElementById('config-form').addEventListener('submit', saveConfig);
    document.getElementById('delete-memory').addEventListener('click', deleteMemory);
    document.getElementById('add-group').addEventListener('click', addGroup);

    // 回复率滑块实时更新显示的值
    const ranRepSlider = document.getElementById('ran-rep-probability');
    const ranRepValue = document.getElementById('ran-rep-value');

    ranRepSlider.addEventListener('input', function() {
        ranRepValue.textContent = this.value + '%';
        // 根据概率值改变颜色
        const value = parseInt(this.value);
        if (value <= 25) {
            ranRepValue.style.background = 'var(--danger-color)';
        } else if (value <= 50) {
            ranRepValue.style.background = 'var(--warning-color)';
        } else if (value <= 75) {
            ranRepValue.style.background = 'var(--info-color)';
        } else {
            ranRepValue.style.background = 'var(--success-color)';
        }
    });

    // 添加输入表单的动画效果
    const formControls = document.querySelectorAll('.form-control, .form-select');
    formControls.forEach(element => {
        element.addEventListener('focus', function() {
            this.classList.add('focused');
        });
        element.addEventListener('blur', function() {
            this.classList.remove('focused');
        });
    });
});

// 初始化滚动动画
function initScrollAnimation() {
    const revealElements = document.querySelectorAll('.reveal');

    const revealOnScroll = function() {
        for (let i = 0; i < revealElements.length; i++) {
            const windowHeight = window.innerHeight;
            const elementTop = revealElements[i].getBoundingClientRect().top;
            const elementVisible = 150;

            if (elementTop < windowHeight - elementVisible) {
                revealElements[i].classList.add('active');
            }
        }
    };

    window.addEventListener('scroll', revealOnScroll);
    // 初始触发一次，以显示首屏内容
    revealOnScroll();
}

// 初始化主题切换功能
function initThemeToggle() {
    const themeToggle = document.getElementById('theme-toggle');
    const icon = themeToggle.querySelector('i');

    // 检查本地存储中的主题设置
    isDarkMode = localStorage.getItem('darkMode') === 'true';

    // 应用保存的主题
    if (isDarkMode) {
        document.body.classList.add('dark-mode');
        icon.classList.remove('fa-moon');
        icon.classList.add('fa-sun');
    }

    themeToggle.addEventListener('click', function() {
        isDarkMode = !isDarkMode;
        document.body.classList.toggle('dark-mode');

        // 切换图标
        if (isDarkMode) {
            icon.classList.remove('fa-moon');
            icon.classList.add('fa-sun');
        } else {
            icon.classList.remove('fa-sun');
            icon.classList.add('fa-moon');
        }

        // 保存主题设置到本地存储
        localStorage.setItem('darkMode', isDarkMode);
    });
}

// 显示通知提示
function showNotification(message, type = 'success') {
    // 创建通知元素
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.innerHTML = `
        <div class="notification-icon">
            <i class="fas ${type === 'success' ? 'fa-check-circle' : type === 'warning' ? 'fa-exclamation-triangle' : 'fa-times-circle'}"></i>
        </div>
        <div class="notification-content">${message}</div>
    `;

    // 添加到页面
    document.body.appendChild(notification);

    // 显示动画
    setTimeout(() => {
        notification.classList.add('show');
    }, 10);

    // 自动关闭
    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => {
            notification.remove();
        }, 300);
    }, 3000);
}

// 更新状态显示，添加动画效果
function updateStatus() {
    fetch('/api/status')
        .then(response => response.json())
        .then(data => {
            const statusBadge = document.getElementById('status-badge');
            const statusText = data.status === 'online' ? '在线' : '离线';
            const statusIcon = data.status === 'online' ?
                '<i class="fas fa-check-circle me-2"></i>' :
                '<i class="fas fa-times-circle me-2"></i>';

            statusBadge.innerHTML = statusIcon + statusText;
            statusBadge.className = 'status-badge badge ' +
                (data.status === 'online' ? 'status-online' : 'status-offline');

            // 使用动画过渡更新信息
            updateWithAnimation('last-activity', data.last_activity);
            updateWithAnimation('memory-count', data.memory_count);
            updateWithAnimation('current-llm', data.current_llm || '未知');
        })
        .catch(error => {
            console.error('获取状态失败:', error);
            showNotification('获取状态信息失败，请检查网络连接', 'error');
        });
}

// 带动画效果的内容更新
function updateWithAnimation(elementId, newContent) {
    const element = document.getElementById(elementId);
    if (element.textContent !== newContent && element.textContent !== '加载中...') {
        element.classList.add('updating');
        setTimeout(() => {
            element.textContent = newContent;
            element.classList.remove('updating');
        }, 300);
    } else if (element.textContent === '加载中...' || element.innerHTML.includes('loading')) {
        element.textContent = newContent;
    }
}

// 加载配置
function loadConfig() {
    fetch('/api/config')
        .then(response => response.json())
        .then(data => {
            // 基本配置
            document.getElementById('websocket-uri').value = data.WEBSOCKET_URI || '';
            document.getElementById('self-user-id').value = data.SELF_USER_ID || '';
            document.getElementById('message-count').value = data.MESSAGE_COUNT || 1;
            document.getElementById('history-timeout').value = data.HISTORY_TIMEOUT || 600;

            // 随机回复率
            const slider = document.getElementById('ran-rep-probability');
            slider.value = data.RAN_REP_PROBABILITY || 0;
            const ranRepValue = document.getElementById('ran-rep-value');
            ranRepValue.textContent = slider.value + '%';

            // 根据概率值设置颜色
            const value = parseInt(slider.value);
            if (value <= 25) {
                ranRepValue.style.background = 'var(--danger-color)';
            } else if (value <= 50) {
                ranRepValue.style.background = 'var(--warning-color)';
            } else if (value <= 75) {
                ranRepValue.style.background = 'var(--info-color)';
            } else {
                ranRepValue.style.background = 'var(--success-color)';
            }

            // 提示词选项
            promptOptions = data.PROMPT || [];
            const promptSelect = document.getElementById('current-prompt');
            promptSelect.innerHTML = '';
            promptOptions.forEach((prompt, index) => {
                const option = document.createElement('option');
                option.value = index;
                // 显示提示词的前20个字符作为预览
                const previewText = prompt ? prompt.substring(0, 20) + '...' : '空提示词';
                option.textContent = `提示词 ${index}: ${previewText}`;
                promptSelect.appendChild(option);
            });

            // 设置当前选中的提示词
            promptSelect.value = data.CURRENT_PROMPT || 0;

            // LLM选项
            llmOptions = data.LLM || {};
            const llmSelect = document.getElementById('current-completion');
            llmSelect.innerHTML = '';

            for (const key in llmOptions) {
                const option = document.createElement('option');
                option.value = key;
                option.textContent = `${key} (${llmOptions[key].NAME})`;
                llmSelect.appendChild(option);
            }

            // 设置当前选中的LLM
            llmSelect.value = data.CURRENT_COMPLETION || '';

            // 加载群聊白名单
            loadGroups(data.ALLOWED_GROUPS || []);

            showNotification('配置加载完成', 'success');
        })
        .catch(error => {
            console.error('加载配置失败:', error);
            showNotification('加载配置失败，请检查网络连接', 'error');
        });
}

// 加载群聊白名单
function loadGroups(groups) {
    const tableBody = document.getElementById('groups-table').getElementsByTagName('tbody')[0];
    tableBody.innerHTML = '';

    if (groups.length === 0) {
        const row = tableBody.insertRow();
        const cell = row.insertCell(0);
        cell.colSpan = 2;
        cell.className = 'text-center text-muted';
        cell.innerHTML = '<i class="fas fa-info-circle me-2"></i>暂无群聊白名单';
        return;
    }

    groups.forEach(groupId => {
        const row = tableBody.insertRow();

        // 创建带有动画效果的单元格
        const idCell = row.insertCell(0);
        idCell.textContent = groupId;
        idCell.className = 'group-id';

        const actionsCell = row.insertCell(1);
        actionsCell.innerHTML = `
            <button class="btn btn-sm btn-danger delete-group" data-id="${groupId}">
                <i class="fas fa-trash-alt me-1"></i>删除
            </button>
        `;

        // 为删除按钮添加事件
        actionsCell.querySelector('.delete-group').addEventListener('click', function() {
            if (confirm(`确定要删除群号: ${groupId} 吗？`)) {
                // 添加删除动画
                row.classList.add('deleting');
                setTimeout(() => {
                    removeGroup(groupId);
                }, 300);
            }
        });
    });
}

// 添加群聊
function addGroup() {
    const groupId = document.getElementById('new-group-id').value;
    if (!groupId || isNaN(parseInt(groupId))) {
        showNotification('请输入有效的群号', 'error');
        return;
    }

    fetch('/api/groups', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ groupId: parseInt(groupId) })
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            document.getElementById('new-group-id').value = '';
            loadConfig(); // 重新加载配置
            showNotification('群聊已成功添加', 'success');
        } else {
            showNotification('添加失败: ' + data.message, 'error');
        }
    })
    .catch(error => {
        console.error('添加群聊错误:', error);
        showNotification('发生错误，请查看控制台', 'error');
    });
}

// 删除群聊
function removeGroup(groupId) {
    fetch(`/api/groups/${groupId}`, {
        method: 'DELETE'
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            loadConfig(); // 重新加载配置
            showNotification('群聊已成功删除', 'success');
        } else {
            showNotification('删除失败: ' + data.message, 'error');
        }
    })
    .catch(error => {
        console.error('删除群聊错误:', error);
        showNotification('发生错误，请查看控制台', 'error');
    });
}

// 保存配置
function saveConfig(event) {
    event.preventDefault();

    // 添加保存中的视觉反馈
    const saveButton = event.target.querySelector('button[type="submit"]');
    const originalText = saveButton.innerHTML;
    saveButton.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>保存中...';
    saveButton.disabled = true;

    const config = {
        WEBSOCKET_URI: document.getElementById('websocket-uri').value,
        SELF_USER_ID: document.getElementById('self-user-id').value,
        MESSAGE_COUNT: parseInt(document.getElementById('message-count').value) || 1,
        RAN_REP_PROBABILITY: parseInt(document.getElementById('ran-rep-probability').value),
        HISTORY_TIMEOUT: parseInt(document.getElementById('history-timeout').value) || 600,
        CURRENT_PROMPT: parseInt(document.getElementById('current-prompt').value) || 0,
        CURRENT_COMPLETION: document.getElementById('current-completion').value
    };

    fetch('/api/config', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(config)
    })
    .then(response => response.json())
    .then(data => {
        // 恢复按钮状态
        saveButton.innerHTML = originalText;
        saveButton.disabled = false;

        if (data.status === 'success') {
            showNotification('配置已成功保存', 'success');
        } else {
            showNotification('保存失败: ' + data.message, 'error');
        }
    })
    .catch(error => {
        console.error('保存配置错误:', error);
        // 恢复按钮状态
        saveButton.innerHTML = originalText;
        saveButton.disabled = false;
        showNotification('发生错误，请查看控制台', 'error');
    });
}

// 加载记忆数据
function loadMemories() {
    fetch('/api/memory')
        .then(response => response.json())
        .then(data => {
            memoryData = data;
            const tableBody = document.getElementById('memory-table').getElementsByTagName('tbody')[0];
            tableBody.innerHTML = '';

            if (Object.keys(data).length === 0) {
                const row = tableBody.insertRow();
                const cell = row.insertCell(0);
                cell.colSpan = 3;
                cell.className = 'text-center text-muted';
                cell.innerHTML = '<i class="fas fa-info-circle me-2"></i>暂无记忆数据';
                return;
            }

            for (const id in data) {
                const row = tableBody.insertRow();
                row.className = 'memory-row';

                const idCell = row.insertCell(0);
                idCell.textContent = id;
                idCell.className = 'memory-id';

                // 生成内容预览
                const preview = Object.keys(data[id]).slice(0, 2).map(key => {
                    const text = data[id][key] || '';
                    return `${key}: ${text.substring(0, 20)}${text.length > 20 ? '...' : ''}`;
                }).join(', ');

                const previewCell = row.insertCell(1);
                previewCell.textContent = preview || '(空)';
                previewCell.className = 'memory-preview';

                const actionsCell = row.insertCell(2);
                actionsCell.innerHTML = `
                    <button class="btn btn-sm btn-info view-memory me-2" data-id="${id}">
                        <i class="fas fa-eye me-1"></i>查看
                    </button>
                    <button class="btn btn-sm btn-danger delete-memory-direct" data-id="${id}">
                        <i class="fas fa-trash-alt me-1"></i>删除
                    </button>
                `;

                // 为每个查看按钮添加事件
                actionsCell.querySelector('.view-memory').addEventListener('click', function() {
                    showMemoryDetail(id);
                });

                // 为每个删除按钮添加事件
                actionsCell.querySelector('.delete-memory-direct').addEventListener('click', function() {
                    if (confirm(`确定要删除 ID: ${id} 的记忆吗？`)) {
                        // 添加删除动画
                        row.classList.add('deleting');
                        setTimeout(() => {
                            deleteMemoryById(id);
                        }, 300);
                    }
                });
            }
        })
        .catch(error => {
            console.error('加载记忆失败:', error);
            showNotification('加载记忆数据失败，请检查网络连接', 'error');
        });
}

// 显示记忆详情
function showMemoryDetail(id) {
    currentMemoryId = id;
    const memoryDetail = document.getElementById('memory-detail');
    const memory = memoryData[id];

    // 显示加载动画
    memoryDetail.innerHTML = `
        <div class="text-center p-5">
            <i class="fas fa-spinner fa-spin fa-2x"></i>
            <p class="mt-3">加载记忆数据...</p>
        </div>
    `;

    // 显示模态框
    const modal = new bootstrap.Modal(document.getElementById('memoryModal'));
    modal.show();

    // 模拟加载延迟，增强用户体验
    setTimeout(() => {
        if (memory) {
            let detailText = '';
            for (const key in memory) {
                detailText += `<div class="memory-item">
                    <div class="memory-key">${key}:</div>
                    <div class="memory-value">${memory[key] || '(空)'}</div>
                </div>`;
            }
            memoryDetail.innerHTML = detailText || '<div class="text-muted text-center">(无内容)</div>';
        } else {
            memoryDetail.innerHTML = '<div class="text-danger text-center"><i class="fas fa-exclamation-circle me-2"></i>找不到记忆数据</div>';
        }
    }, 500);
}

// 删除记忆
function deleteMemory() {
    if (currentMemoryId && confirm(`确定要删除 ID: ${currentMemoryId} 的记忆吗？`)) {
        // 添加删除中的视觉反馈
        const deleteButton = document.getElementById('delete-memory');
        const originalText = deleteButton.innerHTML;
        deleteButton.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>删除中...';
        deleteButton.disabled = true;

        deleteMemoryById(currentMemoryId);

        // 关闭模态框
        setTimeout(() => {
            const modal = bootstrap.Modal.getInstance(document.getElementById('memoryModal'));
            modal.hide();

            // 恢复按钮状态
            deleteButton.innerHTML = originalText;
            deleteButton.disabled = false;
        }, 500);
    }
}

// 按ID删除记忆
function deleteMemoryById(id) {
    fetch(`/api/memory/${id}`, {
        method: 'DELETE'
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            loadMemories(); // 重新加载记忆列表
            showNotification('记忆已成功删除', 'success');
        } else {
            showNotification('删除失败: ' + data.message, 'error');
        }
    })
    .catch(error => {
        console.error('删除记忆错误:', error);
        showNotification('发生错误，请查看控制台', 'error');
    });
}

// 启动机器人
function startBot() {
    // 添加启动中的视觉反馈
    const startButton = document.getElementById('start-bot');
    const originalText = startButton.innerHTML;
    startButton.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>启动中...';
    startButton.disabled = true;

    fetch('/api/bot/start', {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        // 恢复按钮状态
        setTimeout(() => {
            startButton.innerHTML = originalText;
            startButton.disabled = false;
        }, 500);

        showNotification(data.message, data.status === 'success' ? 'success' : 'error');
        updateStatus();
    })
    .catch(error => {
        console.error('启动机器人错误:', error);
        // 恢复按钮状态
        startButton.innerHTML = originalText;
        startButton.disabled = false;
        showNotification('发生错误，请查看控制台', 'error');
    });
}

// 停止机器人
function stopBot() {
    // 添加停止中的视觉反馈
    const stopButton = document.getElementById('stop-bot');
    const originalText = stopButton.innerHTML;
    stopButton.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>停止中...';
    stopButton.disabled = true;

    fetch('/api/bot/stop', {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        // 恢复按钮状态
        setTimeout(() => {
            stopButton.innerHTML = originalText;
            stopButton.disabled = false;
        }, 500);

        showNotification(data.message, data.status === 'success' ? 'success' : 'error');
        updateStatus();
    })
    .catch(error => {
        console.error('停止机器人错误:', error);
        // 恢复按钮状态
        stopButton.innerHTML = originalText;
        stopButton.disabled = false;
        showNotification('发生错误，请查看控制台', 'error');
    });
}

// 添加通知样式到CSS
document.addEventListener('DOMContentLoaded', function() {
    const styleSheet = document.createElement('style');
    styleSheet.textContent = `
        /* 通知样式 */
        .notification {
            position: fixed;
            top: 20px;
            right: 20px;
            display: flex;
            align-items: center;
            background-color: white;
            border-radius: 8px;
            padding: 15px;
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.2);
            transform: translateX(120%);
            transition: transform 0.3s ease;
            z-index: 1000;
            max-width: 350px;
        }
        
        .notification.show {
            transform: translateX(0);
        }
        
        .notification-icon {
            margin-right: 15px;
            font-size: 20px;
        }
        
        .notification-success .notification-icon {
            color: var(--success-color);
        }
        
        .notification-error .notification-icon {
            color: var(--danger-color);
        }
        
        .notification-warning .notification-icon {
            color: var(--warning-color);
        }
        
        .notification-content {
            flex: 1;
        }
        
        /* 动画相关样式 */
        .updating {
            opacity: 0.5;
            transition: opacity 0.3s;
        }
        
        .focused {
            transform: translateY(-3px);
            box-shadow: 0 0 0 0.25rem rgba(159, 134, 192, 0.3) !important;
        }
        
        .deleting {
            opacity: 0;
            transform: translateX(50px);
            transition: all 0.3s;
        }
        
        .memory-row, .group-id {
            transition: background-color 0.3s;
        }
        
        .memory-item {
            margin-bottom: 15px;
            border-bottom: 1px solid rgba(0,0,0,0.1);
            padding-bottom: 10px;
        }
        
        .memory-key {
            font-weight: bold;
            color: var(--primary-color);
            margin-bottom: 5px;
        }
        
        .memory-value {
            white-space: pre-wrap;
            font-family: 'Quicksand', monospace;
            padding: 8px;
            background-color: rgba(0,0,0,0.03);
            border-radius: 4px;
        }
        
        /* 暗色模式下的调整 */
        body.dark-mode .memory-value {
            background-color: rgba(255,255,255,0.05);
        }
        
        body.dark-mode .notification {
            background-color: var(--card-bg);
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.4);
        }
    `;
    document.head.appendChild(styleSheet);
});
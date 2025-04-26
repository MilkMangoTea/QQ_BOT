// 全局变量
let currentMemoryId = null;
let memoryData = {};

// DOM 加载完成后执行
document.addEventListener('DOMContentLoaded', function() {
    // 初始化界面
    updateStatus();
    loadConfig();
    loadMemories();

    // 每10秒更新一次状态
    setInterval(updateStatus, 10000);

    // 绑定事件
    document.getElementById('start-bot').addEventListener('click', startBot);
    document.getElementById('stop-bot').addEventListener('click', stopBot);
    document.getElementById('config-form').addEventListener('submit', saveConfig);
    document.getElementById('delete-memory').addEventListener('click', deleteMemory);

    // 回复率滑块实时更新显示的值
    const ranRepSlider = document.getElementById('ran-rep-probability');
    const ranRepValue = document.getElementById('ran-rep-value');

    ranRepSlider.addEventListener('input', function() {
        ranRepValue.textContent = this.value + '%';
    });
});

// 更新状态显示
function updateStatus() {
    fetch('/api/status')
        .then(response => response.json())
        .then(data => {
            const statusBadge = document.getElementById('status-badge');
            statusBadge.textContent = data.status === 'online' ? '在线' : '离线';
            statusBadge.className = 'status-badge badge ' +
                (data.status === 'online' ? 'status-online' : 'status-offline');

            document.getElementById('last-activity').textContent = data.last_activity;
            document.getElementById('memory-count').textContent = data.memory_count;
        })
        .catch(error => console.error('获取状态失败:', error));
}

// 加载配置
function loadConfig() {
    fetch('/api/config')
        .then(response => response.json())
        .then(data => {
            document.getElementById('websocket-uri').value = data.WEBSOCKET_URI || '';
            document.getElementById('self-user-id').value = data.SELF_USER_ID || '';

            const slider = document.getElementById('ran-rep-probability');
            slider.value = data.RAN_REP_PROBABILITY || 50;
            document.getElementById('ran-rep-value').textContent = slider.value + '%';
        })
        .catch(error => console.error('加载配置失败:', error));
}

// 保存配置
function saveConfig(event) {
    event.preventDefault();

    const config = {
        WEBSOCKET_URI: document.getElementById('websocket-uri').value,
        SELF_USER_ID: document.getElementById('self-user-id').value,
        RAN_REP_PROBABILITY: parseInt(document.getElementById('ran-rep-probability').value)
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
        if (data.status === 'success') {
            alert('配置已保存');
        } else {
            alert('保存失败: ' + data.message);
        }
    })
    .catch(error => {
        console.error('保存配置错误:', error);
        alert('发生错误，请查看控制台');
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

            for (const id in data) {
                const row = tableBody.insertRow();
                row.insertCell(0).textContent = id;

                // 生成内容预览
                const preview = Object.keys(data[id]).slice(0, 2).map(key =>
                    `${key}: ${data[id][key].substring(0, 30)}...`
                ).join(', ');

                row.insertCell(1).textContent = preview || '(空)';

                const actionsCell = row.insertCell(2);
                actionsCell.innerHTML = `
                    <button class="btn btn-sm btn-info view-memory" data-id="${id}">查看</button>
                    <button class="btn btn-sm btn-danger delete-memory-direct" data-id="${id}">删除</button>
                `;

                // 为每个查看按钮添加事件
                actionsCell.querySelector('.view-memory').addEventListener('click', function() {
                    showMemoryDetail(id);
                });

                // 为每个删除按钮添加事件
                actionsCell.querySelector('.delete-memory-direct').addEventListener('click', function() {
                    if (confirm(`确定要删除 ID: ${id} 的记忆吗？`)) {
                        deleteMemoryById(id);
                    }
                });
            }
        })
        .catch(error => console.error('加载记忆失败:', error));
}

// 显示记忆详情
function showMemoryDetail(id) {
    currentMemoryId = id;
    const memoryDetail = document.getElementById('memory-detail');
    const memory = memoryData[id];

    if (memory) {
        let detailText = '';
        for (const key in memory) {
            detailText += `${key}:\n${memory[key]}\n\n`;
        }
        memoryDetail.textContent = detailText || '(无内容)';
    } else {
        memoryDetail.textContent = '找不到记忆数据';
    }

    // 显示模态框
    const modal = new bootstrap.Modal(document.getElementById('memoryModal'));
    modal.show();
}

// 删除记忆
function deleteMemory() {
    if (currentMemoryId && confirm(`确定要删除 ID: ${currentMemoryId} 的记忆吗？`)) {
        deleteMemoryById(currentMemoryId);

        // 关闭模态框
        const modal = bootstrap.Modal.getInstance(document.getElementById('memoryModal'));
        modal.hide();
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
            alert('记忆已删除');
        } else {
            alert('删除失败: ' + data.message);
        }
    })
    .catch(error => {
        console.error('删除记忆错误:', error);
        alert('发生错误，请查看控制台');
    });
}

// 启动机器人
function startBot() {
    fetch('/api/bot/start', {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        alert(data.message);
        updateStatus();
    })
    .catch(error => {
        console.error('启动机器人错误:', error);
        alert('发生错误，请查看控制台');
    });
}

// 停止机器人
function stopBot() {
    fetch('/api/bot/stop', {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        alert(data.message);
        updateStatus();
    })
    .catch(error => {
        console.error('停止机器人错误:', error);
        alert('发生错误，请查看控制台');
    });
}
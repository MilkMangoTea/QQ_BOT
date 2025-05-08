import signal
from flask import Flask, render_template, jsonify, request
import json
import subprocess
import os
import time
import re
from core.function_memory import LocalDictStore
import config
from my_proxy import update_status

# 定义PID文件路径
PID_FILE = os.path.join(os.path.dirname(__file__), "data", "bot.pid")

app = Flask(__name__,
            template_folder="web/templates",
            static_folder="web/static")

# 全局状态变量
bot_status = {
    "running": False,
    "connections": {},
    "last_activity": 0,
    "memory_count": 0
}

# 首页
@app.route('/')
def index():
    return render_template('index.html')

# 获取机器人状态
@app.route('/api/status')
def get_status():
    memory_store = LocalDictStore()

    # 尝试从状态文件读取状态
    status_file = os.path.join(os.path.dirname(__file__), "data", "bot_status.json")
    if os.path.exists(status_file):
        try:
            with open(status_file, "r", encoding="utf-8") as f:
                status_data = json.load(f)

                return jsonify({
                    "status": status_data.get("status", "offline"),
                    "connections": status_data.get("connections", {}),
                    "last_activity": time.strftime('%Y-%m-%d %H:%M:%S',
                                                   time.localtime(status_data.get("last_activity", 0))),
                    "memory_count": status_data.get("memory_count", 0),
                    "current_llm": config.LLM[config.CURRENT_COMPLETION]["NAME"] if hasattr(config,
                                                                                            "CURRENT_COMPLETION") else "未知"
                })
        except Exception as e:
            print(f"读取状态文件错误: {e}")

    # 如果无法从文件读取，返回基本状态
    bot_status["memory_count"] = len(memory_store.list_ids())

    return jsonify({
        "status": "offline",
        "connections": bot_status["connections"],
        "last_activity": time.strftime('%Y-%m-%d %H:%M:%S',
                                       time.localtime(bot_status["last_activity"]))
        if bot_status["last_activity"] else "从未",
        "memory_count": bot_status["memory_count"],
        "current_llm": config.LLM[config.CURRENT_COMPLETION]["NAME"] if hasattr(config, "CURRENT_COMPLETION") else "未知"
    })


# 获取配置
@app.route('/api/config')
def get_config():
    # 从config.py中提取可编辑的配置
    editable_config = {
        "WEBSOCKET_URI": config.WEBSOCKET_URI,
        "SELF_USER_ID": config.SELF_USER_ID,
        "MESSAGE_COUNT": config.MESSAGE_COUNT,
        "RAN_REP_PROBABILITY": config.RAN_REP_PROBABILITY,
        "HISTORY_TIMEOUT": config.HISTORY_TIMEOUT,
        "CURRENT_PROMPT": config.CURRENT_PROMPT,
        "PROMPT": config.PROMPT,
        "CURRENT_COMPLETION": config.CURRENT_COMPLETION,
        "LLM": {k: {"NAME": v["NAME"]} for k, v in config.LLM.items()},  # 只发送名称信息，不发送敏感的API Keys
        "ALLOWED_GROUPS": config.ALLOWED_GROUPS
    }
    return jsonify(editable_config)


# 更新配置
@app.route('/api/config', methods=['POST'])
def update_config():
    data = request.json

    try:
        # 读取当前config.py文件内容
        config_path = os.path.join(os.path.dirname(__file__), "config.py")
        with open(config_path, "r", encoding="utf-8") as f:
            config_content = f.read()

        # 更新配置内容
        # 使用正则表达式替换相应的配置值
        if "WEBSOCKET_URI" in data:
            config_content = re.sub(
                r'WEBSOCKET_URI\s*=\s*[\'"].*[\'"]',
                f'WEBSOCKET_URI = "{data["WEBSOCKET_URI"]}"',
                config_content
            )

        if "SELF_USER_ID" in data:
            config_content = re.sub(
                r'SELF_USER_ID\s*=\s*.*',
                f'SELF_USER_ID = int(os.environ.get("BOT_QQ_ID"))',  # 保持环境变量引用
                config_content
            )

        if "MESSAGE_COUNT" in data:
            config_content = re.sub(
                r'MESSAGE_COUNT\s*=\s*\d+',
                f'MESSAGE_COUNT = {data["MESSAGE_COUNT"]}',
                config_content
            )

        if "RAN_REP_PROBABILITY" in data:
            config_content = re.sub(
                r'RAN_REP_PROBABILITY\s*=\s*\d+',
                f'RAN_REP_PROBABILITY = {data["RAN_REP_PROBABILITY"]}',
                config_content
            )

        if "HISTORY_TIMEOUT" in data:
            config_content = re.sub(
                r'HISTORY_TIMEOUT\s*=\s*\d+',
                f'HISTORY_TIMEOUT = {data["HISTORY_TIMEOUT"]}',
                config_content
            )

        if "CURRENT_PROMPT" in data:
            config_content = re.sub(
                r'CURRENT_PROMPT\s*=\s*\d+',
                f'CURRENT_PROMPT = {data["CURRENT_PROMPT"]}',
                config_content
            )

        if "CURRENT_COMPLETION" in data:
            config_content = re.sub(
                r'CURRENT_COMPLETION\s*=\s*[\'"].*[\'"]',
                f'CURRENT_COMPLETION = "{data["CURRENT_COMPLETION"]}"',
                config_content
            )

        # 写回配置文件
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(config_content)

        # 重新加载配置
        import importlib
        import config
        importlib.reload(config)

        # 向机器人进程发送信号以重新加载配置
        if bot_status["running"] and 'bot_process' in globals():
            try:
                os.kill(bot_process.pid, signal.SIGUSR1)
                return jsonify({"status": "success", "message": "配置已更新，已通知机器人重新加载"})
            except Exception as e:
                return jsonify({"status": "error", "message": f"配置已保存，但通知机器人失败: {str(e)}"})

        return jsonify({"status": "success", "message": "配置已更新并重新加载"})
    except Exception as e:
        print(f"更新配置文件错误: {e}")
        return jsonify({"status": "error", "message": f"更新失败: {str(e)}"})


# 管理群聊白名单
@app.route('/api/groups', methods=['POST'])
def add_group():
    data = request.json

    if 'groupId' not in data or not isinstance(data['groupId'], int):
        return jsonify({"status": "error", "message": "无效的群号"})

    try:
        import config

        # 读取当前config.py文件内容
        config_path = os.path.join(os.path.dirname(__file__), "config.py")
        with open(config_path, "r", encoding="utf-8") as f:
            config_content = f.read()

        # 查找ALLOWED_GROUPS
        match = re.search(r'ALLOWED_GROUPS\s*=\s*\[(.*?)\]', config_content, re.DOTALL)
        if not match:
            return jsonify({"status": "error", "message": "无法找到群聊白名单配置"})

        # 检查群号是否已存在
        existing_groups = config.ALLOWED_GROUPS
        if data['groupId'] in existing_groups:
            return jsonify({"status": "error", "message": "该群号已在白名单中"})

        # 更新白名单
        groups_str = match.group(1)
        new_groups_str = groups_str
        if groups_str.strip():  # 如果不为空
            new_groups_str = groups_str + f", {data['groupId']}"
        else:
            new_groups_str = f"{data['groupId']}"

        # 替换配置
        config_content = config_content.replace(
            f"ALLOWED_GROUPS = [{groups_str}]",
            f"ALLOWED_GROUPS = [{new_groups_str}]"
        )

        # 写回配置文件
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(config_content)

        # 重新加载配置
        import importlib
        import config
        importlib.reload(config)

        return jsonify({"status": "success", "message": "群聊已添加到白名单"})
    except Exception as e:
        print(f"添加群聊错误: {e}")
        return jsonify({"status": "error", "message": f"添加失败: {str(e)}"})


# 删除群聊
@app.route('/api/groups/<int:group_id>', methods=['DELETE'])
def remove_group(group_id):
    try:
        import config

        # 读取当前config.py文件内容
        config_path = os.path.join(os.path.dirname(__file__), "config.py")
        with open(config_path, "r", encoding="utf-8") as f:
            config_content = f.read()

        # 检查群号是否存在
        existing_groups = config.ALLOWED_GROUPS
        if group_id not in existing_groups:
            return jsonify({"status": "error", "message": "该群号不在白名单中"})

        # 更新群聊白名单列表
        updated_groups = [g for g in existing_groups if g != group_id]
        updated_groups_str = ", ".join(str(g) for g in updated_groups)

        # 替换配置
        config_content = re.sub(
            r'ALLOWED_GROUPS\s*=\s*\[.*?\]',
            f'ALLOWED_GROUPS = [{updated_groups_str}]',
            config_content,
            flags=re.DOTALL
        )

        # 写回配置文件
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(config_content)

        # 重新加载配置
        import importlib
        import config
        importlib.reload(config)

        return jsonify({"status": "success", "message": "群聊已从白名单移除"})
    except Exception as e:
        print(f"删除群聊错误: {e}")
        return jsonify({"status": "error", "message": f"删除失败: {str(e)}"})


# 查看记忆内容
@app.route('/api/memory')
def get_memory():
    memory_store = LocalDictStore()
    memory_data = {}

    for id in memory_store.list_ids():
        memory_data[id] = memory_store.get_record(id)

    return jsonify(memory_data)


# 删除记忆
@app.route('/api/memory/<id>', methods=['DELETE'])
def delete_memory(id):
    try:
        memory_store = LocalDictStore()
        memory_store.delete_record(id)
        return jsonify({"status": "success", "message": f"记忆 {id} 已删除"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"删除失败: {str(e)}"})


# 检查机器人是否在运行
def check_bot_status():
    # 如果PID文件存在，认为机器人在运行
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            # 简单检查进程是否存在
            try:
                os.kill(pid, 0)  # 不发送信号，只检查进程是否存在
                return True, pid
            except OSError:  # 进程不存在
                os.remove(PID_FILE)  # 清理无效的PID文件
                return False, None
        except:
            # 读取PID失败，清理文件
            os.remove(PID_FILE)
            return False, None
    return False, None


# 启动bot进程的函数
def start_bot_process():
    # 创建data目录（如果不存在）
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    global bot_process
    bot_process = subprocess.Popen(["python", "my_proxy.py"])

    # 记录PID到文件中
    with open(PID_FILE, "w") as f:
        f.write(str(bot_process.pid))

    bot_status["running"] = True
    return bot_process


# 停止bot进程
def stop_bot_process():
    running, pid = check_bot_status()
    if running:
        try:
            # 尝试终止进程
            import signal
            os.kill(pid, signal.SIGTERM)

            update_status("offline")
            print("🚫 程序已终止")
            # 删除PID文件
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
            bot_status["running"] = False
            return True
        except:
            return False
    return False


# 启动Bot API
@app.route('/api/bot/start', methods=['POST'])
def start_bot():
    running, _ = check_bot_status()

    if running:
        return jsonify({"status": "info", "message": "机器人已在运行"})

    try:
        start_bot_process()
        return jsonify({"status": "success", "message": "机器人已启动"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"启动失败: {str(e)}"})


# 停止Bot API
@app.route('/api/bot/stop', methods=['POST'])
def stop_bot():
    if stop_bot_process():
        return jsonify({"status": "success", "message": "机器人已停止"})
    else:
        return jsonify({"status": "error", "message": "停止失败或机器人未在运行"})


# 在服务器启动时检查状态
running, _ = check_bot_status()
bot_status["running"] = running

if __name__ == "__main__":
    import logging

    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)  # 只显示错误信息
    app.run(debug = True)
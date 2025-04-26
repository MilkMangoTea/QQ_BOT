from flask import Flask, render_template, jsonify, request, redirect, url_for
import threading
import json
import os
import time
from core.function_memory import LocalDictStore
from config import *
from my_proxy import LLM_NAME

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


# 启动bot进程的函数(如果需要从web页面启动bot)
def start_bot_process():
    import subprocess
    global bot_process
    bot_process = subprocess.Popen(["python", "my_proxy.py"])
    bot_status["running"] = True
    return bot_process


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
                    "memory_count": status_data.get("memory_count", 0)
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
        "memory_count": bot_status["memory_count"]
    })


# 获取配置
@app.route('/api/config')
def get_config():
    # 从config.py中提取可编辑的配置
    editable_config = {
        "WEBSOCKET_URI": WEBSOCKET_URI,
        "SELF_USER_ID": SELF_USER_ID,
        "TARGET_USER_ID": TARGET_USER_ID,
        "RAN_REP_PROBABILITY": RAN_REP_PROBABILITY,
        "HISTORY_TIMEOUT": HISTORY_TIMEOUT,
        "MESSAGE_COUNT": MESSAGE_COUNT,
        "EMOJI_POOL": EMOJI_POOL[:5],  # 只显示前5个
        "CURRENT_LLM": LLM_NAME if 'LLM_NAME' in globals() else "未设置"
    }
    return jsonify(editable_config)


# 更新配置
@app.route('/api/config', methods=['POST'])
def update_config():
    data = request.json

    # 在实际应用中，这里应该将配置写回config.py
    # 注意：这需要文件I/O权限，可能存在安全风险

    return jsonify({"status": "success", "message": "配置已更新"})


# 查看记忆内容
@app.route('/api/memory')
def get_memory():
    memory_store = LocalDictStore()
    memory_data = {}

    for id in memory_store.list_ids():
        memory_data[id] = memory_store.get_record(id)

    return jsonify(memory_data)


# 启动Bot
@app.route('/api/bot/start', methods=['POST'])
def start_bot():
    if not bot_status["running"]:
        try:
            start_bot_process()
            return jsonify({"status": "success", "message": "机器人已启动"})
        except Exception as e:
            return jsonify({"status": "error", "message": f"启动失败: {str(e)}"})
    return jsonify({"status": "info", "message": "机器人已在运行"})


# 停止Bot
@app.route('/api/bot/stop', methods=['POST'])
def stop_bot():
    global bot_process
    if bot_status["running"] and 'bot_process' in globals():
        try:
            bot_process.terminate()
            bot_status["running"] = False
            return jsonify({"status": "success", "message": "机器人已停止"})
        except Exception as e:
            return jsonify({"status": "error", "message": f"停止失败: {str(e)}"})
    return jsonify({"status": "info", "message": "机器人未在运行"})




if __name__ == "__main__":
    app.run(debug = True)
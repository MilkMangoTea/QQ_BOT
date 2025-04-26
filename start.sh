#!/bin/bash

# 创建数据目录
mkdir -p data

# 检查是否要启动Web服务
if [ "$1" == "web" ] || [ "$1" == "all" ]; then
    echo "正在启动Web管理界面..."
    python web_server.py &
    WEB_PID=$!
    echo "Web服务已启动，PID: $WEB_PID"
fi

# 检查是否要启动QQ机器人
if [ "$1" == "bot" ] || [ "$1" == "all" ] || [ "$#" -eq 0 ]; then
    echo "正在启动QQ机器人..."
    python my_proxy.py &
    BOT_PID=$!
    echo "QQ机器人已启动，PID: $BOT_PID"
fi

echo "服务已启动，按Ctrl+C停止"

# 等待用户中断
trap "kill $WEB_PID $BOT_PID 2>/dev/null" INT
wait
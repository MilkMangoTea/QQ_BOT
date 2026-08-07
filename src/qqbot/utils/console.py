def out(title, content=None):
    """输出统一格式的运行日志。"""
    if content is None:
        print(f"----------\n{title}\n----------")
        return

    print(f"----------\n{title}\n{content}\n----------")

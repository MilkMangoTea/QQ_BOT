import numpy as np
from langchain_core.tools import tool


@tool
def numpy_calc(expression: str) -> str:
    """MUST use this tool for ANY mathematical calculations including matrix operations, trigonometry, statistics, etc. DO NOT calculate manually.

    Args:
        expression: Python expression using numpy (np) functions

    Examples:
        - "np.array([[1,2],[3,4]]) @ np.array([[5],[6]])" - matrix multiplication
        - "np.linalg.inv(np.array([[1,2],[3,4]]))" - matrix inverse
        - "np.sin(np.pi/2)" - trigonometry
        - "np.mean([1,2,3,4,5])" - statistics
    """
    try:
        # 自动更新弃用的 numpy 函数
        expression = expression.replace("np.trapz", "np.trapezoid").replace("numpy.trapz", "numpy.trapezoid")

        safe_namespace = {
            "np": np,
            "numpy": np,
        }
        result = eval(expression, {"__builtins__": {}}, safe_namespace)

        if isinstance(result, np.ndarray):
            return f"计算结果：\n{result}\n形状：{result.shape}"
        else:
            return f"计算结果：{result}"
    except Exception as e:
        return f"计算错误：{str(e)}"


# 导出工具列表
TOOLS = [numpy_calc]
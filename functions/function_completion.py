import base64
import requests
from urllib3.exceptions import InsecureRequestWarning

# 请求构建器
def build_params(type, event, content):
    msg_type = event.get("message_type")
    base = ""
    if type == "text":
        if not content:
            content = "ioi"
        base = {"message": [{"type": "text", "data": {"text": content}}]}
    elif type == "image":
        base = {"message": [{"type": "image", "data": {"file": content, "sub_type": 1, "summary": "[色禽图片]"}}]}
    key = "user_id" if msg_type == "private" else "group_id"
    return {**base, "message_type": msg_type, key: event[key]}

# 图片转换
def url_to_base64(url):
    try:
        url = url.replace("https", "http")

        # 添加常见浏览器User-Agent头以避免被拒绝
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 Edg/132.0.0.0'
        }

        # 发起请求并设置10秒超时
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
        response = requests.get(url, headers=headers, timeout=10, verify=False)
        response.raise_for_status()  # 检查HTTP错误状态码

        # 验证内容类型是否为图片
        content_type = response.headers.get('Content-Type', '')
        if not content_type.startswith('image/'):
            print(f"⚠️ 警告：URL未返回图片内容（Content-Type: {content_type}）")
            return None

        # 编码为Base64字符串
        image_data = response.content
        response.close()
        return base64.b64encode(image_data).decode('utf-8')

    except requests.exceptions.RequestException as e:
        print(f"⚠️ 请求失败: {str(e)}")
    except Exception as e:
        print(f"⚠️ 处理异常: {str(e)}")
    return None
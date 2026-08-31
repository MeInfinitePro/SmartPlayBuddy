import base64

#用于获取base64编码照片
def get_base64(target_path):
    with open(target_path, "rb") as f:
        image_base64 = base64.b64encode(f.read()).decode('utf-8')
    return image_base64

#调用模型
def get_ai_messages(messages:list):
    # 延迟导入 langchain，避免模块在无 langchain 环境下无法导入
    from langchain_community.chat_models.tongyi import ChatTongyi
    # 初始化模型
    model = ChatTongyi(model="qwen-vl-max")  # 或 qwen-vl-max
    response = model.invoke(input=messages)
    return response.content[0]['text']

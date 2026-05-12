def route_message(text: str) -> str:
    text = text.strip()

    if not text:
        return "你可以发送文本。"

    return text

from langchain_core.messages import HumanMessage

from agent.graph import chat_graph, extract_final_text


async def route_message(
    platform: str,
    platform_user_id: str,
    text: str,
    *,
    username: str | None = None,
    display_name: str | None = None,
    language_code: str | None = None,
) -> str:
    text = text.strip()

    if not text:
        return "你可以发送文本。"

    result = await chat_graph.ainvoke(
        {
            "messages": [HumanMessage(content=text)],
            "platform": platform,
            "platform_user_id": platform_user_id,
            "user_id": None,
            "username": username,
            "display_name": display_name,
            "language_code": language_code,
        },
        config={"configurable": {"thread_id": f"{platform}:{platform_user_id}"}},
    )

    return extract_final_text(result["messages"])

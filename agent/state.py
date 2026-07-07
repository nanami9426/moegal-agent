from langgraph.graph import MessagesState


class MoegalState(MessagesState):
    platform: str
    platform_user_id: str
    user_id: int | None
    memory_context: str | None
    username: str | None
    display_name: str | None
    language_code: str | None

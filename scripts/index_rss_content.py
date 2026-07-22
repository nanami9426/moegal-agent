from config.settings import init_settings
from db.session import init_db
from services.rss_pipeline.content_index import (
    get_embedding_model_name,
    index_cached_content,
)


def main() -> None:
    init_settings()
    if get_embedding_model_name() is None:
        raise RuntimeError("请先配置 MOEGAL_EMBEDDING_MODEL。")
    init_db()
    result = index_cached_content()
    print(
        "RSS 向量索引完成："
        f"新增/更新 {result.indexed_items} 条内容、{result.indexed_chunks} 个分块，"
        f"跳过 {result.unchanged_items} 条未变化内容，"
        f"放弃 {result.stale_items} 条并发变更内容。"
    )


if __name__ == "__main__":
    main()

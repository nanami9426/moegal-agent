import json
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session

from db.models import User
from services.account.memories import remember_memory, retrieve_memories


CASES_PATH = Path(__file__).parents[1] / "tests" / "fixtures" / "memory_retrieval_cases.json"


def main() -> None:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    hits = 0
    expected_total = 0
    with ExitStack() as stack:
        stack.enter_context(patch("services.account.memories.get_engine", return_value=engine))
        for index, case in enumerate(cases, start=1):
            user_id = 1_000_000_000 + index
            with Session(engine) as session:
                session.add(
                    User(
                        id=user_id,
                        platform="eval",
                        platform_user_id=str(index),
                    )
                )
                session.commit()
            for memory in case["memories"]:
                remember_memory(user_id=user_id, **memory)

            retrieved = retrieve_memories(user_id, case["query"], limit=1)
            retrieved_keys = {memory.key for memory in retrieved}
            expected_keys = set(case["expected_keys"])
            hits += len(retrieved_keys & expected_keys)
            expected_total += len(expected_keys)

    recall = hits / expected_total if expected_total else 1.0
    print(
        json.dumps(
            {
                "cases": len(cases),
                "expected_memories": expected_total,
                "hits": hits,
                "recall_at_1": round(recall, 4),
            },
            ensure_ascii=False,
        )
    )
    if recall < 1.0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

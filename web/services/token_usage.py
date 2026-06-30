from sqlalchemy import func
from sqlmodel import Session, select

from db.models import LLMTokenUsage
from web.schemas import (
    TokenUsageByModelItem,
    TokenUsageRecordItem,
    TokenUsageResponse,
    TokenUsageSummary,
)


def build_token_usage(
    session: Session,
    user_id: int,
    *,
    recent_limit: int,
) -> TokenUsageResponse:
    summary_row = session.exec(
        select(
            func.count(LLMTokenUsage.id),
            func.coalesce(func.sum(LLMTokenUsage.prompt_tokens), 0),
            func.coalesce(func.sum(LLMTokenUsage.completion_tokens), 0),
            func.coalesce(func.sum(LLMTokenUsage.total_tokens), 0),
            func.coalesce(func.avg(LLMTokenUsage.elapsed_ms), 0),
            func.max(LLMTokenUsage.created_at),
        ).where(LLMTokenUsage.user_id == user_id)
    ).one()

    model_rows = session.exec(
        select(
            LLMTokenUsage.model,
            func.count(LLMTokenUsage.id),
            func.coalesce(func.sum(LLMTokenUsage.prompt_tokens), 0),
            func.coalesce(func.sum(LLMTokenUsage.completion_tokens), 0),
            func.coalesce(func.sum(LLMTokenUsage.total_tokens), 0),
        )
        .where(LLMTokenUsage.user_id == user_id)
        .group_by(LLMTokenUsage.model)
        .order_by(func.sum(LLMTokenUsage.total_tokens).desc(), LLMTokenUsage.model)
    ).all()

    recent = session.exec(
        select(LLMTokenUsage)
        .where(LLMTokenUsage.user_id == user_id)
        .order_by(LLMTokenUsage.created_at.desc(), LLMTokenUsage.id.desc())
        .limit(recent_limit)
    ).all()

    return TokenUsageResponse(
        summary=TokenUsageSummary(
            request_count=int(summary_row[0] or 0),
            prompt_tokens=int(summary_row[1] or 0),
            completion_tokens=int(summary_row[2] or 0),
            total_tokens=int(summary_row[3] or 0),
            average_elapsed_ms=round(float(summary_row[4] or 0)),
            latest_created_at=summary_row[5],
        ),
        by_model=[
            TokenUsageByModelItem(
                model=row[0],
                request_count=int(row[1] or 0),
                prompt_tokens=int(row[2] or 0),
                completion_tokens=int(row[3] or 0),
                total_tokens=int(row[4] or 0),
            )
            for row in model_rows
        ],
        recent=[
            TokenUsageRecordItem.model_validate(record)
            for record in recent
        ],
    )

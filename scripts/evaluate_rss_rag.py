import json
from pathlib import Path

from config.settings import init_settings
from services.rss_pipeline.retrieval import search_rss_content


QUESTIONS_PATH = Path(__file__).resolve().parents[1] / "evals" / "rss_rag_questions.json"


def main() -> None:
    init_settings()
    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    reports: list[dict[str, object]] = []
    result_cases = 0
    linked_results = 0
    result_count = 0
    judged_cases = 0
    keyword_hits = 0

    for case in questions:
        results = search_rss_content(
            case["query"],
            days=case["days"],
            limit=5,
        )
        if results:
            result_cases += 1
        result_count += len(results)
        linked_results += sum(bool(result.source_url) for result in results)

        expected_keywords = case["expected_keywords"]
        keyword_hit: bool | None = None
        if expected_keywords:
            judged_cases += 1
            searchable = " ".join(
                " ".join(value for value in (result.title, result.excerpt) if value)
                for result in results
            ).casefold()
            keyword_hit = any(
                keyword.casefold() in searchable for keyword in expected_keywords
            )
            keyword_hits += int(keyword_hit)

        reports.append(
            {
                "id": case["id"],
                "query": case["query"],
                "result_count": len(results),
                "keyword_hit": keyword_hit,
                "results": [
                    {
                        "title": result.title,
                        "url": result.source_url,
                        "matched_by": result.matched_by,
                    }
                    for result in results
                ],
            }
        )

    summary = {
        "case_count": len(questions),
        "result_rate": _ratio(result_cases, len(questions)),
        "source_link_rate": _ratio(linked_results, result_count),
        "keyword_hit_rate": _ratio(keyword_hits, judged_cases),
        "embedding_enabled": any(
            "semantic" in result["matched_by"]
            for report in reports
            for result in report["results"]
        ),
    }
    print(json.dumps({"summary": summary, "cases": reports}, ensure_ascii=False, indent=2))


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


if __name__ == "__main__":
    main()

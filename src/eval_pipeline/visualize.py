from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd
import seaborn as sns

from eval_pipeline.models import RowResult

logger = logging.getLogger(__name__)

DIFFICULTY_ORDER = ["easy", "medium", "hard", "unknown"]
QUERY_TYPE_ORDER = ["factual", "analytical", "procedural", "unknown"]


def render_chart(records: list[RowResult], output_path: Path) -> None:
    if not records:
        logger.warning("No records to chart")
        return

    rows = []
    for r in records:
        rows.append(
            {
                "query_type": r.record.query_type or "unknown",
                "difficulty": r.record.difficulty or "unknown",
                "composite_score": r.composite.score,
            }
        )
    df = pd.DataFrame(rows)

    agg = df.groupby(["difficulty", "query_type"], as_index=False)["composite_score"].mean()

    plt.figure(figsize=(10, 6))
    sns.barplot(
        data=agg,
        x="difficulty",
        y="composite_score",
        hue="query_type",
        order=[d for d in DIFFICULTY_ORDER if d in agg["difficulty"].unique()],
        hue_order=[q for q in QUERY_TYPE_ORDER if q in agg["query_type"].unique()],
    )
    plt.title("Agent Quality by Query Type and Difficulty")
    plt.xlabel("Difficulty")
    plt.ylabel("Mean Composite Score")
    plt.ylim(0, 1.0)
    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=100)
    plt.close()
    logger.info("Chart saved to %s", output_path)

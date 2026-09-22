"""Financial news sentiment extraction and feature generation."""

import logging
import re
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

BULLISH_TERMS = {
    "surge", "surges", "surged", "surging", "jump", "jumps", "jumped", "rally", "rallies", "rallied",
    "gain", "gains", "gained", "rise", "rises", "rising", "rose", "soar", "soars", "soared",
    "profit", "profits", "profitable", "growth", "grow", "grows", "record", "beat", "beats",
    "upgrade", "upgrades", "upgraded", "bullish", "outperform", "dividend", "buyback", "boost",
    "expansion", "milestone", "strong", "recovery", "positive", "high", "success", "innovative"
}

BEARISH_TERMS = {
    "plunge", "plunges", "plunged", "drop", "drops", "dropped", "fall", "falls", "falling", "fell",
    "slump", "slumps", "slumped", "decline", "declines", "declined", "loss", "losses", "miss", "misses",
    "missed", "downgrade", "downgrades", "downgraded", "bearish", "underperform", "crash", "crashes",
    "probe", "investigation", "fraud", "penalty", "default", "debt", "warning", "warns", "warned",
    "weak", "layoff", "layoffs", "cut", "cuts", "negative", "low", "risk", "uncertainty", "crisis"
}


class SentimentFeatureExtractor:
    """Extracts sentiment polarity scores from financial news items and aggregates them by date."""

    def score_text(self, text: str) -> float:
        """Scores text sentiment in range [-1.0, 1.0] using financial lexicon."""
        if not text:
            return 0.0

        words = re.findall(r"\b[a-zA-Z]+\b", text.lower())
        if not words:
            return 0.0

        pos_count = sum(1 for w in words if w in BULLISH_TERMS)
        neg_count = sum(1 for w in words if w in BEARISH_TERMS)

        total_sentiment_words = pos_count + neg_count
        if total_sentiment_words == 0:
            return 0.0

        score = (pos_count - neg_count) / float(total_sentiment_words)
        return float(np.clip(score, -1.0, 1.0))

    def process_news_items(self, news_items: List[Dict[str, Any]]) -> pd.DataFrame:
        """Aggregates a list of news items into a daily sentiment DataFrame."""
        if not news_items:
            return pd.DataFrame(columns=["Date", "News_Sentiment_Score", "News_Count", "News_Sentiment_5d_Mean"])

        records = []
        for item in news_items:
            date_str = item.get("date")
            if not date_str:
                continue

            text = f"{item.get('title', '')} {item.get('summary', '')}"
            score = self.score_text(text)
            records.append({
                "Date": pd.to_datetime(date_str),
                "score": score,
            })

        if not records:
            return pd.DataFrame(columns=["Date", "News_Sentiment_Score", "News_Count", "News_Sentiment_5d_Mean"])

        news_df = pd.DataFrame(records)
        daily = news_df.groupby("Date").agg(
            News_Sentiment_Score=("score", "mean"),
            News_Count=("score", "count"),
        ).reset_index()

        daily = daily.sort_values("Date").reset_index(drop=True)
        daily["News_Sentiment_5d_Mean"] = daily["News_Sentiment_Score"].rolling(window=5, min_periods=1).mean()

        return daily

"""
News / sentiment filter.

Design intent: SMC/ICT price action is the PRIMARY signal. This module is a
VETO layer only — it can block a trade that price action likes if the macro
news/sentiment backdrop is strongly against it. It should never invent trades
on its own, because headline-driven signals are noisy and easy to overfit.

Data sources supported (bring your own API key via config.py / env vars):
  - NewsAPI.org headline search (general macro/financial headlines)
  - Alpha Vantage NEWS_SENTIMENT endpoint (has a built-in sentiment score,
    including central-bank and company-level news)
  - X (Twitter) API v2 recent search (requires elevated/paid access for
    reliable real-time coverage of specific accounts)

None of this can promise you'll catch a market-moving tweet the second it
posts — that depends entirely on your API tier and polling frequency. Treat
it as directional color, not a timing signal.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

import requests

import config

logger = logging.getLogger("sentiment")

# Very small default lexicon as an offline fallback if you don't want to wire
# up a real sentiment model. Swap in a proper NLP sentiment model (e.g. a
# finance-tuned transformer) for anything serious.
_POSITIVE_WORDS = {
    "cut", "cuts", "dovish", "stimulus", "easing", "growth", "beat", "beats",
    "strong", "rally", "optimism", "deal", "agreement", "support", "bullish",
}
_NEGATIVE_WORDS = {
    "hike", "hikes", "hawkish", "tariff", "tariffs", "war", "conflict",
    "sanction", "sanctions", "recession", "default", "crisis", "ban",
    "shutdown", "inflation", "miss", "misses", "weak", "bearish", "sell-off",
}

SYMBOL_KEYWORDS = {
    "EURUSD": ["euro", "ecb", "eurozone", "european central bank"],
    "GBPUSD": ["pound", "boe", "bank of england", "uk economy"],
    "USDJPY": ["yen", "boj", "bank of japan"],
    "XAUUSD": ["gold", "fed", "federal reserve", "safe haven", "interest rate"],
}


@dataclass
class SentimentResult:
    score: float          # roughly -1 (very negative) to +1 (very positive)
    headline_count: int
    sample_headlines: List[str]


def _score_text(text: str) -> float:
    words = text.lower().split()
    pos = sum(1 for w in words if any(p in w for p in _POSITIVE_WORDS))
    neg = sum(1 for w in words if any(n in w for n in _NEGATIVE_WORDS))
    if pos + neg == 0:
        return 0.0
    return (pos - neg) / (pos + neg)


def _fetch_newsapi(keywords: List[str]) -> List[str]:
    if not config.NEWSAPI_KEY:
        return []
    try:
        query = " OR ".join(keywords)
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 15,
                "apiKey": config.NEWSAPI_KEY,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return [a["title"] for a in data.get("articles", []) if a.get("title")]
    except Exception as e:
        logger.warning("NewsAPI fetch failed: %s", e)
        return []


def _fetch_alphavantage(keywords: List[str]) -> List[str]:
    if not config.ALPHAVANTAGE_KEY:
        return []
    try:
        resp = requests.get(
            "https://www.alphavantage.co/query",
            params={
                "function": "NEWS_SENTIMENT",
                "topics": "economy_macro,finance",
                "apikey": config.ALPHAVANTAGE_KEY,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        feed = data.get("feed", [])
        headlines = []
        for item in feed:
            title = item.get("title", "")
            if any(k.lower() in title.lower() for k in keywords):
                headlines.append(title)
        return headlines
    except Exception as e:
        logger.warning("AlphaVantage fetch failed: %s", e)
        return []


def _fetch_x_recent(keywords: List[str]) -> List[str]:
    """
    Pulls recent posts mentioning the given keywords via X API v2 recent search.
    NOTE: to specifically track named individuals or firms (e.g. a market-moving
    account), use the `from:` operator in the query and make sure your API tier
    has access to recent search with sufficient rate limits.
    """
    if not config.X_BEARER_TOKEN:
        return []
    try:
        query = " OR ".join(keywords) + " -is:retweet lang:en"
        resp = requests.get(
            "https://api.twitter.com/2/tweets/search/recent",
            headers={"Authorization": f"Bearer {config.X_BEARER_TOKEN}"},
            params={"query": query, "max_results": 20, "tweet.fields": "created_at"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return [t["text"] for t in data.get("data", [])]
    except Exception as e:
        logger.warning("X API fetch failed: %s", e)
        return []


def get_sentiment(symbol: str) -> Optional[SentimentResult]:
    """Aggregate sentiment across configured sources for a symbol's macro theme."""
    if not config.SENTIMENT_ENABLED:
        return None

    keywords = SYMBOL_KEYWORDS.get(symbol, [symbol])
    headlines = []
    headlines += _fetch_newsapi(keywords)
    headlines += _fetch_alphavantage(keywords)
    headlines += _fetch_x_recent(keywords)

    if not headlines:
        return SentimentResult(score=0.0, headline_count=0, sample_headlines=[])

    scores = [_score_text(h) for h in headlines]
    avg = sum(scores) / len(scores)
    return SentimentResult(score=avg, headline_count=len(headlines), sample_headlines=headlines[:5])


def sentiment_allows_trade(symbol: str, direction: str) -> bool:
    """
    Veto check. direction is "buy" or "sell".
    A "buy" is blocked if sentiment is strongly negative; a "sell" is blocked
    if sentiment is strongly positive. Neutral/insufficient data never blocks.
    """
    result = get_sentiment(symbol)
    if result is None or result.headline_count == 0:
        return True  # no data => don't block on it

    if direction == "buy" and result.score <= config.SENTIMENT_VETO_THRESHOLD:
        logger.info("Sentiment veto: %s buy blocked, score=%.2f (%s)", symbol, result.score, result.sample_headlines[:2])
        return False
    if direction == "sell" and result.score >= -config.SENTIMENT_VETO_THRESHOLD:
        logger.info("Sentiment veto: %s sell blocked, score=%.2f (%s)", symbol, result.score, result.sample_headlines[:2])
        return False
    return True

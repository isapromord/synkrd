"""
SynkDR Engine — Analytics Engine

Tracks real metrics: response times, resolution rates, conversation counts.
Replaces the fabricated "85%" with actual measured data.
"""

import logging
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger("synkdr.analytics")


class AnalyticsEngine:
    """
    In-memory analytics collector with periodic DB flush.
    
    Tracks:
    - Response latency (per tier)
    - Conversations started/resolved/escalated per day
    - Resolution rate (conversations closed without escalation)
    - Messages per conversation
    """

    def __init__(self):
        self._events: list = []
        self._daily_stats: dict = defaultdict(lambda: {
            "conversations_started": 0,
            "conversations_resolved": 0,
            "conversations_escalated": 0,
            "messages_total": 0,
            "response_times_ms": [],
            "tier1_count": 0,
            "tier2_count": 0,
        })

    def _today_key(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def track_message(self, tier: int, latency_ms: int, intent: str, channel: str) -> None:
        """Track a single message interaction."""
        day = self._today_key()
        stats = self._daily_stats[day]
        stats["messages_total"] += 1
        stats["response_times_ms"].append(latency_ms)
        if tier == 1:
            stats["tier1_count"] += 1
        elif tier == 2:
            stats["tier2_count"] += 1

        self._events.append({
            "type": "message",
            "tier": tier,
            "latency_ms": latency_ms,
            "intent": intent,
            "channel": channel,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def track_conversation_start(self, channel: str) -> None:
        """Track a new conversation starting."""
        day = self._today_key()
        self._daily_stats[day]["conversations_started"] += 1
        self._events.append({
            "type": "conversation_start",
            "channel": channel,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def track_conversation_resolved(self) -> None:
        """Track a conversation resolved without escalation."""
        day = self._today_key()
        self._daily_stats[day]["conversations_resolved"] += 1

    def track_escalation(self, level: int, reason: str) -> None:
        """Track an escalation event."""
        day = self._today_key()
        self._daily_stats[day]["conversations_escalated"] += 1
        self._events.append({
            "type": "escalation",
            "level": level,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get_live_stats(self) -> dict:
        """Get current day's live statistics."""
        day = self._today_key()
        stats = self._daily_stats[day]

        response_times = stats["response_times_ms"]
        avg_latency = int(sum(response_times) / len(response_times)) if response_times else 0
        under_3s = sum(1 for t in response_times if t < 3000)
        pct_under_3s = round((under_3s / len(response_times)) * 100) if response_times else 0

        started = stats["conversations_started"]
        resolved = stats["conversations_resolved"]
        escalated = stats["conversations_escalated"]
        resolution_rate = round((resolved / started) * 100) if started > 0 else 0

        return {
            "date": day,
            "conversations_started": started,
            "conversations_resolved": resolved,
            "conversations_escalated": escalated,
            "resolution_rate_pct": resolution_rate,
            "messages_total": stats["messages_total"],
            "avg_response_ms": avg_latency,
            "pct_under_3s": pct_under_3s,
            "tier1_pct": round((stats["tier1_count"] / stats["messages_total"]) * 100) if stats["messages_total"] else 0,
            "tier2_pct": round((stats["tier2_count"] / stats["messages_total"]) * 100) if stats["messages_total"] else 0,
        }

    def get_summary(self, days: int = 7) -> dict:
        """Get aggregated stats over the last N days."""
        today = datetime.now(timezone.utc).date()
        total_started = 0
        total_resolved = 0
        total_escalated = 0
        total_messages = 0
        all_latencies = []

        for i in range(days):
            day_key = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            if day_key in self._daily_stats:
                s = self._daily_stats[day_key]
                total_started += s["conversations_started"]
                total_resolved += s["conversations_resolved"]
                total_escalated += s["conversations_escalated"]
                total_messages += s["messages_total"]
                all_latencies.extend(s["response_times_ms"])

        avg_latency = int(sum(all_latencies) / len(all_latencies)) if all_latencies else 0
        resolution_rate = round((total_resolved / total_started) * 100) if total_started > 0 else 0
        under_3s = sum(1 for t in all_latencies if t < 3000)
        pct_under_3s = round((under_3s / len(all_latencies)) * 100) if all_latencies else 0

        return {
            "period_days": days,
            "conversations_started": total_started,
            "conversations_resolved": total_resolved,
            "conversations_escalated": total_escalated,
            "resolution_rate_pct": resolution_rate,
            "messages_total": total_messages,
            "avg_response_ms": avg_latency,
            "pct_under_3s": pct_under_3s,
        }

    def to_db_rows(self) -> list:
        """Export daily stats as rows matching Supabase analytics_daily schema."""
        rows = []
        for day_key, stats in self._daily_stats.items():
            response_times = stats["response_times_ms"]
            total_latency = int(sum(response_times)) if response_times else 0
            started = stats["conversations_started"]
            resolved = stats["conversations_resolved"]
            under_3s = sum(1 for t in response_times if t < 3000)

            rows.append({
                "date": day_key,
                "conversations_started": started,
                "conversations_resolved": resolved,
                "escalations": stats.get("conversations_escalated", 0),
                "messages_total": stats.get("messages_total", 0),
                "total_latency_ms": total_latency,
                "messages_under_3s": under_3s,
                "messages_tier_1": stats.get("tier1_count", 0),
                "messages_tier_2": stats.get("tier2_count", 0),
            })
        return rows


# Singleton instance
analytics = AnalyticsEngine()

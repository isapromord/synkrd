"""
SynkDR Engine — Conversation State Machine

Manages conversation flow and state transitions.
States: greeting → browsing → interested → buying → post_sale
"""

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger("elisa.state")


class ConversationState(str, Enum):
    """Customer journey states."""
    GREETING = "greeting"           # First contact
    BROWSING = "browsing"           # Looking at products
    INTERESTED = "interested"       # Asking detailed questions
    BUYING = "buying"               # Ready to purchase
    POST_SALE = "post_sale"         # After purchase (order status, returns)
    ESCALATED = "escalated"         # Handed off to human
    INACTIVE = "inactive"           # No response in 24h+


class Conversation:
    """
    Represents a single conversation session with a customer.

    Attributes:
        customer_id: Phone number or session ID
        state: Current conversation state
        history: List of messages [{role, content, timestamp}]
        product_interests: Products the customer asked about
        metadata: Extra info (channel, language, etc.)
    """

    def __init__(
        self,
        customer_id: str,
        channel: str = "whatsapp",
        state: ConversationState = ConversationState.GREETING,
        db_id: Optional[str] = None,
    ):
        self.id = db_id
        self.customer_id = customer_id
        self.channel = channel
        self.state = state
        self.history: list = []
        self.product_interests: list = []
        self.metadata: dict = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_active": datetime.now(timezone.utc).isoformat(),
            "message_count": 0,
            "escalation_level": 0,
        }

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the conversation history."""
        self.history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.metadata["message_count"] += 1
        self.metadata["last_active"] = datetime.now(timezone.utc).isoformat()

    def add_product_interest(self, product_name: str) -> None:
        """Track which products the customer is interested in."""
        if product_name not in self.product_interests:
            self.product_interests.append(product_name)

    def get_history_for_ai(self, max_messages: int = 10) -> list:
        """Get conversation history formatted for AI engines."""
        return [
            {"role": msg["role"], "content": msg["content"]}
            for msg in self.history[-max_messages:]
        ]

    def transition_state(self, intent: str) -> ConversationState:
        """
        Transition conversation state based on detected intent.
        Returns the new state.
        """
        old_state = self.state

        # State transition rules
        transitions = {
            ConversationState.GREETING: {
                "pricing": ConversationState.INTERESTED,
                "product_info": ConversationState.BROWSING,
                "catalog": ConversationState.BROWSING,
                "shipping": ConversationState.INTERESTED,
                "greeting": ConversationState.GREETING,
                "purchase": ConversationState.BUYING,
                "escalation": ConversationState.ESCALATED,
            },
            ConversationState.BROWSING: {
                "pricing": ConversationState.INTERESTED,
                "product_info": ConversationState.BROWSING,
                "payment": ConversationState.BUYING,
                "purchase": ConversationState.BUYING,
                "shipping": ConversationState.INTERESTED,
                "escalation": ConversationState.ESCALATED,
            },
            ConversationState.INTERESTED: {
                "payment": ConversationState.BUYING,
                "purchase": ConversationState.BUYING,
                "negotiation": ConversationState.INTERESTED,
                "complex_comparison": ConversationState.INTERESTED,
                "post_sale_issue": ConversationState.POST_SALE,
                "escalation": ConversationState.ESCALATED,
            },
            ConversationState.BUYING: {
                "shipping": ConversationState.BUYING,
                "payment": ConversationState.BUYING,
                "post_sale_issue": ConversationState.POST_SALE,
                "escalation": ConversationState.ESCALATED,
            },
            ConversationState.POST_SALE: {
                "product_info": ConversationState.BROWSING,
                "escalation": ConversationState.ESCALATED,
                "frustration": ConversationState.ESCALATED,
            },
        }

        # Get valid transitions for current state
        valid = transitions.get(self.state, {})
        new_state = valid.get(intent, self.state)  # Stay in same state if no match

        if new_state != old_state:
            logger.info(
                f"🔄 State transition: {old_state.value} → {new_state.value} "
                f"| customer={self.customer_id} | trigger={intent}"
            )
            self.state = new_state

        return self.state

    def to_dict(self) -> dict:
        """Serialize conversation for database storage."""
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "channel": self.channel,
            "state": self.state.value,
            "history": self.history,
            "product_interests": self.product_interests,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Conversation":
        """Deserialize conversation from database."""
        conv = cls(
            customer_id=data["customer_id"],
            channel=data.get("channel", "whatsapp"),
            state=ConversationState(data.get("state", "greeting")),
            db_id=data.get("id"),
        )
        conv.history = data.get("history", [])
        conv.product_interests = data.get("product_interests", [])
        conv.metadata = data.get("metadata", {})
        return conv

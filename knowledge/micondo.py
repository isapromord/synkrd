"""
Elisa — Mi Condo Knowledge Source (BotForge v1)

Fetches condominium data from Supabase and performs Legal RAG.
This is the PLUGGABLE knowledge layer for the condominium domain.

Uses a SEPARATE Supabase project from Sofia/TrendyRD.
"""

import os
import logging
from typing import Optional
from datetime import datetime, timezone

logger = logging.getLogger("elisa.knowledge.micondo")

# Mi Condo Supabase client (separate from Sofia's)
_micondo_client = None


def get_micondo_supabase():
    """Lazy-initialize Mi Condo Supabase client."""
    global _micondo_client
    if _micondo_client is None:
        try:
            from supabase import create_client

            url = os.getenv("MICONDO_SUPABASE_URL", "")
            key = os.getenv("MICONDO_SUPABASE_KEY", "")

            if not url or not key:
                logger.warning("⚠️ Mi Condo Supabase URL or KEY not configured")
                return None

            _micondo_client = create_client(url, key)
            logger.info("✅ Mi Condo Supabase client initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Mi Condo Supabase: {e}")
    return _micondo_client


class MiCondoKnowledge:
    """
    Mi Condo Supabase integration for condominium knowledge.

    Provides data queries for both resident and admin flows.
    All reads go through Supabase RLS (Row Level Security).
    """

    def __init__(self):
        self.client = get_micondo_supabase()

    # ═══════════════════════════════════════════════════════════
    # RESIDENT QUERIES
    # ═══════════════════════════════════════════════════════════

    async def get_unit_by_phone(self, phone: str) -> Optional[dict]:
        """
        Find a unit by owner WhatsApp number.
        Used to identify which resident is messaging.
        """
        if not self.client:
            return None

        try:
            # Normalize phone (remove +, spaces, dashes)
            normalized = phone.replace("+", "").replace(" ", "").replace("-", "").strip()

            result = self.client.table("units").select(
                "*, condos(id, name, code, company_id)"
            ).or_(
                f"owner_whatsapp.eq.{normalized},"
                f"owner_whatsapp.eq.+{normalized},"
                f"owner_phones.ilike.%{normalized[-10:]}%"
            ).limit(1).execute()

            if result.data:
                return result.data[0]
        except Exception as e:
            logger.error(f"❌ Unit phone lookup failed: {e}")

        return None

    async def get_unit_balance(self, unit_id: str) -> dict:
        """
        Calculate unit balance from account_history.
        Returns: { balance, last_charge_date, last_charge_desc, entries }
        """
        if not self.client:
            return {"balance": 0, "entries": []}

        try:
            result = self.client.table("account_history").select("*").eq(
                "unit_id", unit_id
            ).order("date", desc=True).execute()

            entries = result.data or []

            # Calculate balance: Cargo (+) increases debt, Abono (-) reduces debt
            balance = 0
            for entry in entries:
                amount = float(entry.get("amount", 0))
                if entry.get("type") == "Cargo":
                    balance += amount
                elif entry.get("type") == "Abono":
                    balance -= amount

            last_charge = next(
                (e for e in entries if e.get("type") == "Cargo"), None
            )

            return {
                "balance": balance,
                "last_charge_date": last_charge["date"] if last_charge else None,
                "last_charge_desc": last_charge.get("description", "") if last_charge else "",
                "entries": entries[:10],  # Last 10 entries
            }
        except Exception as e:
            logger.error(f"❌ Balance calculation failed: {e}")
            return {"balance": 0, "entries": []}

    async def get_communications(self, condo_id: str, limit: int = 5) -> list:
        """Get recent communications/circulares for a condo."""
        if not self.client:
            return []

        try:
            result = self.client.table("communications").select("*").eq(
                "condo_id", condo_id
            ).order("date", desc=True).limit(limit).execute()

            return result.data or []
        except Exception as e:
            logger.error(f"❌ Communications fetch failed: {e}")
            return []

    async def get_amenities(self, condo_id: str) -> list:
        """Get available amenities for a condo."""
        if not self.client:
            return []

        try:
            result = self.client.table("amenities").select("*").eq(
                "condo_id", condo_id
            ).execute()

            return result.data or []
        except Exception as e:
            logger.error(f"❌ Amenities fetch failed: {e}")
            return []

    async def create_incident(
        self, condo_id: str, description: str, reported_by: str
    ) -> Optional[dict]:
        """Create a new incident report."""
        if not self.client:
            return None

        try:
            result = self.client.table("incidents").insert({
                "condo_id": condo_id,
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "reported_by": reported_by,
                "description": description,
                "status": "Abierto",
            }).execute()

            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"❌ Incident creation failed: {e}")
            return None

    async def create_reservation(
        self,
        unit_id: str,
        amenity_id: str,
        date: str,
        start_time: str,
        end_time: str,
    ) -> Optional[dict]:
        """Create a new amenity reservation."""
        if not self.client:
            return None

        try:
            # Check for conflicts
            existing = self.client.table("reservations").select("id").eq(
                "amenity_id", amenity_id
            ).eq("date", date).neq(
                "status", "Rechazada"
            ).execute()

            # Simple overlap detection: if any reservation exists on that date
            if existing.data:
                return {"conflict": True, "existing": existing.data}

            result = self.client.table("reservations").insert({
                "unit_id": unit_id,
                "amenity_id": amenity_id,
                "date": date,
                "start_time": start_time,
                "end_time": end_time,
                "status": "Pendiente",
            }).execute()

            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"❌ Reservation creation failed: {e}")
            return None

    async def submit_payment_notification(
        self,
        unit_id: str,
        condo_id: str,
        amount: float,
        payment_date: str,
        notes: str = "",
    ) -> Optional[dict]:
        """Submit a payment notification (comprobante de pago)."""
        if not self.client:
            return None

        try:
            result = self.client.table("payment_notifications").insert({
                "unit_id": unit_id,
                "condo_id": condo_id,
                "amount": amount,
                "payment_date": payment_date,
                "notes": notes,
                "status": "Pendiente",
            }).execute()

            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"❌ Payment notification failed: {e}")
            return None

    # ═══════════════════════════════════════════════════════════
    # ADMIN QUERIES
    # ═══════════════════════════════════════════════════════════

    async def get_delinquent_units(self, condo_id: str) -> list:
        """
        Get units with outstanding balances (morosos).
        Returns list of units with their calculated balance > 0.
        """
        if not self.client:
            return []

        try:
            # Get all units for the condo
            units_result = self.client.table("units").select(
                "id, apartment_number, owner_name, monthly_fee"
            ).eq("condo_id", condo_id).eq("status", "Activo").execute()

            delinquent = []
            for unit in (units_result.data or []):
                balance_data = await self.get_unit_balance(unit["id"])
                if balance_data["balance"] > 0:
                    delinquent.append({
                        **unit,
                        "balance": balance_data["balance"],
                        "last_charge_date": balance_data.get("last_charge_date"),
                    })

            # Sort by balance descending
            delinquent.sort(key=lambda u: u["balance"], reverse=True)
            return delinquent
        except Exception as e:
            logger.error(f"❌ Delinquent units query failed: {e}")
            return []

    async def get_open_incidents(self, condo_id: str) -> dict:
        """Get count and list of open incidents."""
        if not self.client:
            return {"open": 0, "in_progress": 0, "incidents": []}

        try:
            result = self.client.table("incidents").select("*").eq(
                "condo_id", condo_id
            ).in_("status", ["Abierto", "En Progreso"]).order(
                "date", desc=True
            ).execute()

            incidents = result.data or []
            open_count = sum(1 for i in incidents if i["status"] == "Abierto")
            in_progress = sum(1 for i in incidents if i["status"] == "En Progreso")

            return {
                "open": open_count,
                "in_progress": in_progress,
                "incidents": incidents,
            }
        except Exception as e:
            logger.error(f"❌ Open incidents query failed: {e}")
            return {"open": 0, "in_progress": 0, "incidents": []}

    async def get_monthly_summary(
        self, condo_id: str, year: int = None, month: int = None
    ) -> dict:
        """Get financial summary for a given month."""
        if not self.client:
            return {"income": 0, "expenses": 0, "balance": 0}

        now = datetime.now(timezone.utc)
        year = year or now.year
        month = month or now.month

        try:
            # Build date range for the month
            start_date = f"{year}-{month:02d}-01"
            if month == 12:
                end_date = f"{year + 1}-01-01"
            else:
                end_date = f"{year}-{month + 1:02d}-01"

            result = self.client.table("transactions").select("*").eq(
                "condo_id", condo_id
            ).gte("date", start_date).lt("date", end_date).execute()

            transactions = result.data or []

            income = sum(
                float(t["amount"]) for t in transactions if t["type"] == "Ingreso"
            )
            expenses = sum(
                float(t["amount"]) for t in transactions if t["type"] == "Egreso"
            )

            return {
                "income": income,
                "expenses": expenses,
                "balance": income - expenses,
                "transaction_count": len(transactions),
                "year": year,
                "month": month,
            }
        except Exception as e:
            logger.error(f"❌ Monthly summary query failed: {e}")
            return {"income": 0, "expenses": 0, "balance": 0}

    async def get_payroll_status(self, condo_id: str) -> Optional[dict]:
        """Get the latest payroll status."""
        if not self.client:
            return None

        try:
            result = self.client.table("payrolls").select(
                "*, payroll_payments(employee_name, net_pay)"
            ).eq("condo_id", condo_id).order(
                "year", desc=True
            ).order("month", desc=True).limit(1).execute()

            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"❌ Payroll status query failed: {e}")
            return None


# ═══════════════════════════════════════════════════════════════
# CONTEXT BUILDER — Injects condo data into AI prompts
# ═══════════════════════════════════════════════════════════════

def build_condo_context(unit_data: dict, balance_data: dict = None) -> str:
    """
    Build condo context string for AI prompt injection.
    This gives Elisa knowledge about the resident's unit.
    """
    if not unit_data:
        return "No se encontró información de unidad para este número."

    condo = unit_data.get("condos", {})
    lines = [
        f"🏢 Condominio: {condo.get('name', 'N/A')}",
        f"🏠 Unidad: {unit_data.get('apartment_number', 'N/A')}",
        f"👤 Propietario: {unit_data.get('owner_name', 'N/A')}",
        f"💲 Cuota mensual: RD$ {unit_data.get('monthly_fee', 0):,.2f}",
    ]

    if balance_data:
        balance = balance_data.get("balance", 0)
        status = "🟢 Al día" if balance <= 0 else f"🔴 Debe RD$ {balance:,.2f}"
        lines.append(f"📊 Estado: {status}")

        if balance_data.get("last_charge_date"):
            lines.append(
                f"📅 Último cargo: {balance_data['last_charge_date']} — "
                f"{balance_data.get('last_charge_desc', '')}"
            )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# LEGAL KNOWLEDGE — pgvector RAG for Dominican Republic Laws
# ═══════════════════════════════════════════════════════════════

async def generate_embedding(text: str) -> list:
    """
    Generate vector embedding using Gemini API.
    Returns a 768-dimension vector for pgvector storage/search.
    """
    import httpx

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        logger.error("❌ GEMINI_API_KEY not set — cannot generate embeddings")
        return []

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-embedding-001:embedContent?key={api_key}"
    )
    payload = {
        "model": "models/gemini-embedding-001",
        "content": {"parts": [{"text": text}]},
        "outputDimensionality": 768,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            embedding = data.get("embedding", {}).get("values", [])
            if embedding:
                logger.info(f"✅ Embedding generated ({len(embedding)} dims)")
            return embedding
    except Exception as e:
        logger.error(f"❌ Embedding generation failed: {e}")
        return []


async def search_legal_knowledge(
    query: str, limit: int = 3, threshold: float = 0.4
) -> list:
    """
    Semantic search over legal knowledge using pgvector cosine similarity.
    Falls back to keyword search if embedding fails.
    """
    client = get_micondo_supabase()
    if not client:
        return []

    # Try semantic search first
    embedding = await generate_embedding(query)

    if embedding:
        try:
            result = client.rpc(
                "search_legal_knowledge",
                {
                    "query_embedding": embedding,
                    "match_threshold": threshold,
                    "match_count": limit,
                },
            ).execute()

            if result.data:
                logger.info(
                    f"✅ Legal search: {len(result.data)} results for '{query[:50]}...'"
                )
                return result.data
        except Exception as e:
            logger.warning(f"⚠️ Vector search failed, falling back to keywords: {e}")

    # Fallback: keyword search
    try:
        result = client.table("legal_knowledge").select(
            "id, category, law_name, article_number, title, summary, "
            "full_text, applies_to, source, is_pending"
        ).eq("is_active", True).text_search(
            "summary", query, config="spanish"
        ).limit(limit).execute()

        return result.data or []
    except Exception as e:
        logger.error(f"❌ Legal keyword search failed: {e}")
        return []


async def add_legal_entry(entry: dict) -> Optional[dict]:
    """
    Add a new legal knowledge entry with auto-generated embedding.
    Used by admins to upload new laws or update existing ones.

    entry = {
        "category": "condominios",
        "law_name": "Ley 5038",
        "article_number": "Art. 25",
        "title": "Obligación de pago de cuotas",
        "summary": "Los propietarios están obligados a...",
        "full_text": "Artículo 25.- Todo copropietario...",
        "keywords": ["cuota", "pago", "obligación"],
        "applies_to": "resident",
        "source": "Ley 5038-1958",
        "effective_date": "1958-04-18",
        "is_pending": False,
    }
    """
    client = get_micondo_supabase()
    if not client:
        return None

    # Generate embedding from summary + title
    embed_text = f"{entry.get('title', '')}. {entry.get('summary', '')}"
    embedding = await generate_embedding(embed_text)

    if embedding:
        entry["embedding"] = embedding

    try:
        result = client.table("legal_knowledge").insert(entry).execute()
        if result.data:
            logger.info(
                f"✅ Legal entry added: {entry.get('law_name')} {entry.get('article_number', '')}"
            )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"❌ Legal entry insert failed: {e}")
        return None


def format_legal_results(results: list) -> str:
    """Format legal search results for AI context injection."""
    if not results:
        return "No se encontraron artículos legales relevantes."

    lines = ["⚖️ REFERENCIAS LEGALES ENCONTRADAS:"]
    for r in results:
        article = r.get("article_number", "")
        pending = " ⏳ [PENDIENTE DE PROMULGACIÓN]" if r.get("is_pending") else ""
        lines.append(
            f"\n📖 {r['law_name']} {article}{pending}\n"
            f"   Título: {r['title']}\n"
            f"   {r['summary']}\n"
            f"   Fuente: {r['source']}"
        )

    lines.append(
        "\n⚠️ Información orientativa. No constituye asesoría legal profesional."
    )
    return "\n".join(lines)


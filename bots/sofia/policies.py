"""
Sofía — Store Policies (SynkDR Engine)
Bot-specific policy definitions (pluggable per business).
"""

STORE_POLICIES = {
    "shipping": {
        "standard_days": "4-7 días laborables",
        "dispatch": "Siguiente día hábil después de la orden",
        "tracking": True,
        "coverage": "Toda República Dominicana",
        "free_shipping_threshold": None,  # No free shipping threshold yet
    },
    "returns": {
        "window_days": 10,
        "conditions": "Producto sin usar, en empaque original",
        "refund_method": "Reembolso completo o cambio",
        "shipping_cost": "El cliente cubre el envío de devolución",
    },
    "payment": {
        "methods": [
            "Contra entrega (COD) — pago al recibir",
            "Transferencia bancaria",
        ],
        "currency": "RD$ (Pesos Dominicanos)",
        "installments": False,
    },
    "customer_service": {
        "hours": "Lunes a Sábado, 9am - 7pm (hora RD)",
        "response_time": "Dentro de 1 hora en horario laboral",
        "channels": ["WhatsApp", "Web Chat"],
        "owner": "Howard",
    },
}


def get_policy_response(topic: str) -> str:
    """Get a formatted policy response for Sofía to use."""
    policy = STORE_POLICIES.get(topic)
    if not policy:
        return ""

    if topic == "shipping":
        return (
            f"📦 Envío en {policy['standard_days']} con código de seguimiento. "
            f"Se despacha al {policy['dispatch'].lower()}. "
            f"Cobertura: {policy['coverage']}."
        )
    elif topic == "returns":
        return (
            f"🔄 Tienes {policy['window_days']} días para devolver. "
            f"Condición: {policy['conditions']}. "
            f"Recibe {policy['refund_method'].lower()}."
        )
    elif topic == "payment":
        methods = ", ".join(policy["methods"])
        return f"💳 Métodos: {methods}. Precios en {policy['currency']}."
    elif topic == "customer_service":
        return (
            f"🕐 Horario: {policy['hours']}. "
            f"Respuesta en {policy['response_time']}."
        )

    return ""

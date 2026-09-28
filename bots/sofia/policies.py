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
            "Contra entrega (COD) — pago al recibir en efectivo",
            "Transferencia bancaria / depósito",
        ],
        "currency": "RD$ (Pesos Dominicanos) / USD",
        "installments": False,
        "bank_accounts": {
            "beneficiary": "Howard Eduardo Luna Perez",
            "cedula": "40226400022",
            "accounts": [
                {"bank": "Banco Popular", "currency": "DOP", "type": "Corriente", "account": "809372188"},
                {"bank": "Banco BHD", "currency": "DOP", "type": "Ahorros", "account": "37472100011"},
                {"bank": "Banco Promerica", "currency": "USD", "type": "Ahorros", "account": "21921000049373"},
            ]
        },
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
        return f"💳 Métodos de pago: {methods}. ¡La mayoría prefiere pagar contra entrega (en efectivo al recibir)! Si prefieres transferencia, avísame y te paso las cuentas bancarias."
    elif topic == "customer_service":
        return (
            f"🕐 Horario: {policy['hours']}. "
            f"Respuesta en {policy['response_time']}."
        )

    return ""


def get_bank_transfer_instructions() -> str:
    """Format bank accounts clearly for WhatsApp transfer customers."""
    p = STORE_POLICIES["payment"]["bank_accounts"]
    lines = [
        "💳 *Cuentas para Transferencia / Depósito:*",
        f"👤 *Titular:* {p['beneficiary']}",
        f"🆔 *Cédula:* {p['cedula']}",
        "",
    ]
    for acc in p["accounts"]:
        lines.append(f"🏦 *{acc['bank']}* ({acc['currency']})\n   Tipo: {acc['type']} | No: `{acc['account']}`")
    lines.append("\n📸 Al realizar la transferencia, envíame la foto o captura del comprobante por aquí para procesar tu orden de inmediato. ✅")
    return "\n".join(lines)

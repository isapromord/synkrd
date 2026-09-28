"""
SynkDR Engine — Bank Transfer Receipt Validator (AI Vision)

Analyzes bank payment receipts (comprobantes de transferencia) sent by customers
via WhatsApp for Banco Popular, Banco BHD, Banco Promerica, Banreservas, etc.

Uses Gemini / GPT-4o Vision multimodal analysis to:
1. Detect whether the image is actually a Dominican banking receipt / voucher.
2. Verify beneficiary matches Howard Eduardo Luna Perez (Cédula 40226400022 or account numbers).
3. Extract amount, authorization code, date, and sender info.
4. Run anti-fraud / AI alteration inspection:
   - Detect misaligned fonts, suspicious box artifacts, font mismatch on amount,
     AI hallucinations, or fake voucher generator layouts.
"""

import os
import json
import logging
import re
from typing import Optional, Dict, Any

logger = logging.getLogger("synkdr.receipt_validator")

# Official verification targets
OFFICIAL_BENEFICIARY = "Howard Eduardo Luna Perez"
OFFICIAL_CEDULA = "40226400022"
OFFICIAL_ACCOUNTS = {
    "popular": "809372188",
    "bhd": "37472100011",
    "promerica": "21921000049373",
}

RECEIPT_ANALYSIS_PROMPT = """Eres un auditor antifraude y analista experto en comprobantes bancarios de República Dominicana (Banco Popular Dominicano, Banco BHD, Banco Promerica, Banreservas, Scotiabank, APAP, etc.).

Tu tarea es inspeccionar minuciosamente esta imagen enviada por un cliente que afirma haber hecho una transferencia o depósito bancario.

### OBJETIVOS DE ANÁLISIS:
1. ¿Es un comprobante bancario real? (Sí / No)
2. Banco emisor y/o receptor (ej: Banco Popular, BHD, Promerica, Banreservas, ACH, Pago al Instante BCRD).
3. Beneficiario o Cuenta Destino:
   - ¿Aparece el nombre "Howard Eduardo Luna Perez" (o variaciones "Howard Luna", "Howard E. Luna")?
   - ¿Aparece la cédula "40226400022" o terminación similar?
   - ¿Aparece alguna de las cuentas: 809372188, 37472100011, 21921000049373?
4. Monto transferido (número y moneda, ej: 1450.00 DOP o USD).
5. Número de autorización, referencia o transacción (ej: AUTH 883921).
6. Fecha y hora aproximada de la transacción.
7. INSPECCIÓN ANTIFRAUDE Y DETECCIÓN DE EDICIÓN / IA:
   - Revisa si el monto o números tienen una tipografía diferente, tamaño desigual, artefactos de compresión JPEG sospechosos en los números, o bordes pegados (copy-paste / Photoshop).
   - Revisa si parece una imagen sintética generada por Inteligencia Artificial (texto ininteligible, letras deformes, logos distorsionados).
   - Revisa si es una plantilla de apps falsas de transferencias (Fake Transfer Generator).

### RESPONDE EXCLUSIVAMENTE CON UN OBJETO JSON VÁLIDO CON ESTA ESTRUCTURA EXACTA (sin markdown adicional, sin comentarios):
{
  "is_receipt": true,
  "is_authentic": true,
  "confidence_score": 0.95,
  "bank": "Banco Popular",
  "beneficiary_name": "Howard Eduardo Luna Perez",
  "beneficiary_matches_target": true,
  "destination_account": "809372188",
  "amount": 1450.0,
  "currency": "DOP",
  "auth_code": "9812401",
  "timestamp_str": "28/09/2026 18:30",
  "suspicious_flags": [],
  "summary": "Transferencia válida de RD$ 1,450 a Howard Eduardo Luna Perez en Banco Popular."
}

Si la imagen NO es un comprobante de pago, devuelve:
{
  "is_receipt": false,
  "is_authentic": false,
  "confidence_score": 0.0,
  "bank": "Desconocido",
  "beneficiary_name": "",
  "beneficiary_matches_target": false,
  "destination_account": "",
  "amount": 0.0,
  "currency": "DOP",
  "auth_code": "",
  "timestamp_str": "",
  "suspicious_flags": ["NO_RECEIPT_DETECTED"],
  "summary": "La imagen no corresponde a un comprobante bancario."
}
"""


async def validate_payment_receipt(
    image_url: str,
    expected_amount: Optional[float] = None,
    ycloud_api_key: str = "",
) -> Dict[str, Any]:
    """
    Download and inspect a bank transfer receipt using AI Multimodal Vision.

    Args:
        image_url: Public or YCloud URL of the uploaded image.
        expected_amount: Optional order total to verify amount match.
        ycloud_api_key: Auth key if downloading via YCloud.

    Returns:
        Structured inspection result dict.
    """
    try:
        import httpx

        # 1. Download image bytes
        headers = {"X-API-Key": ycloud_api_key} if ycloud_api_key else {}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(image_url, headers=headers, follow_redirects=True)
            if resp.status_code != 200:
                logger.error(f"❌ Failed to download receipt image: HTTP {resp.status_code}")
                return {"is_receipt": False, "error": f"Download failed: {resp.status_code}"}
            image_bytes = resp.content

        if not image_bytes or len(image_bytes) < 1000:
            return {"is_receipt": False, "error": "Image empty or too small"}

        content_type = resp.headers.get("content-type", "")
        if "png" in content_type:
            mime_type = "image/png"
        elif "webp" in content_type:
            mime_type = "image/webp"
        else:
            mime_type = "image/jpeg"

        # 2. Prefer Gemini Vision
        gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        openai_api_key = os.getenv("OPENAI_API_KEY", "")

        raw_json_str = ""

        if gemini_api_key:
            try:
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=gemini_api_key)
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[
                        types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                        RECEIPT_ANALYSIS_PROMPT,
                    ],
                )
                raw_json_str = response.text.strip()
            except Exception as ge:
                logger.warning(f"Gemini receipt analysis fallback to OpenAI: {ge}")

        # Fallback to OpenAI GPT-4o mini / vision if needed
        if not raw_json_str and openai_api_key:
            import base64

            b64_img = base64.b64encode(image_bytes).decode("utf-8")
            async with httpx.AsyncClient(timeout=45) as client:
                res = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {openai_api_key}",
                    },
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": RECEIPT_ANALYSIS_PROMPT},
                                    {
                                        "type": "image_url",
                                        "image_url": {"url": f"data:{mime_type};base64,{b64_img}"},
                                    },
                                ],
                            }
                        ],
                        "max_tokens": 500,
                        "temperature": 0.1,
                    },
                )
                if res.status_code == 200:
                    data = res.json()
                    raw_json_str = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

        if not raw_json_str:
            return {"is_receipt": False, "error": "No vision AI provider responded"}

        # 3. Clean JSON output
        cleaned = re.sub(r"^```json\s*", "", raw_json_str)
        cleaned = re.sub(r"^```\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()

        result = json.loads(cleaned)

        # 4. Cross check against official targets
        beneficiary = str(result.get("beneficiary_name", "")).lower()
        account = str(result.get("destination_account", ""))
        is_target_beneficiary = (
            "howard" in beneficiary
            or "luna" in beneficiary
            or "40226400022" in beneficiary
            or any(acc in account for acc in OFFICIAL_ACCOUNTS.values())
        )
        result["beneficiary_matches_target"] = is_target_beneficiary

        # Cross check amount match if provided
        if expected_amount and expected_amount > 0:
            extracted_amount = float(result.get("amount", 0) or 0)
            diff = abs(extracted_amount - expected_amount)
            # Tolerance of RD$ 10 in case of commissions/cents
            result["amount_matches_order"] = diff <= 15
        else:
            result["amount_matches_order"] = True

        logger.info(
            f"🧾 Receipt evaluated: Bank={result.get('bank')} | "
            f"Amount={result.get('amount')} | Valid={result.get('is_authentic')} | "
            f"MatchesTarget={result.get('beneficiary_matches_target')}"
        )
        return result

    except Exception as e:
        logger.error(f"❌ Error validating payment receipt: {e}", exc_info=True)
        return {
            "is_receipt": False,
            "is_authentic": False,
            "error": str(e),
            "summary": "Error al procesar la imagen del comprobante.",
        }

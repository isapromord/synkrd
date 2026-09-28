#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Sofía Bot — VPS Deployment Script
# Run this INSIDE the VPS after SSH'ing in
# ═══════════════════════════════════════════════════════════════

echo "🚀 Deploying Sofía Bot..."

# 1. Clone the repo
cd /root
git clone https://github.com/lunacodeabit/shopify-bot.git synkdr-bot 2>/dev/null || (cd synkdr-bot && git pull)
cd /root/synkdr-bot

# 2. Create .env (ONLY if it doesn't exist — never overwrite live API keys)
if [ ! -f .env ]; then
cat > .env << 'ENVEOF'
# ═══════════════════════════════════════════════════════════════
# Sofía — TrendyRD Customer Service Bot
# ═══════════════════════════════════════════════════════════════

# --- AI ENGINES ---
GEMINI_API_KEY=AIzaSyBlMoNKBCP8vI0FIYmkqtHWJ0zDg9W2_YA
GEMINI_MODEL=gemini-2.5-flash

ANTHROPIC_API_KEY=
CLAUDE_MODEL=claude-sonnet-4-20250514
CLAUDE_FALLBACK_MODEL=claude-3-5-haiku-20241022

AI_MAX_TOKENS=500
AI_TEMPERATURE=0.3

# --- SUPABASE ---
SUPABASE_URL=https://votyvfjbrjmcghekaatk.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZvdHl2ZmpicmptY2doZWthYXRrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIzOTA3NDksImV4cCI6MjA4Nzk2Njc0OX0.-vo_fUfBzty-mPXn61tv-v8azBcXeL3nF0JBEgYopK0

# --- SHOPIFY ---
SHOPIFY_STORE_URL=synkdr.com

# --- WHATSAPP (YCloud) ---
YCLOUD_API_KEY=
YCLOUD_WEBHOOK_SECRET=
YCLOUD_WABA_ID=
WHATSAPP_FROM_NUMBER=+18296298989

# --- WEB CHAT CORS ---
WEBCHAT_CORS_ORIGINS=https://synkdr.com,https://synkdr.com,http://localhost:3000

# --- ESCALATION ---
OWNER_NAME=Howard

# --- SERVER ---
HOST=0.0.0.0
PORT=8002
SYNC_KEY=sofia_sync_369
ENVEOF

echo "✅ .env created"
else
echo "⏭️  .env already exists — keeping existing keys (not overwritten)"
fi

# 3. Install Python deps
pip3 install -r requirements.txt --quiet
echo "✅ Dependencies installed"

# 4. Create systemd service
cat > /etc/systemd/system/synkdr-bot.service << 'SVCEOF'
[Unit]
Description=SynkDR Engine - AI Customer Service Platform
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/synkdr-bot
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable synkdr-bot
systemctl start synkdr-bot
echo "✅ Service started"

# 5. Create nginx config
cat > /etc/nginx/sites-available/synkdr.com << 'NGXEOF'
server {
    listen 80;
    server_name synkdr.com;

    location / {
        proxy_pass http://127.0.0.1:8002;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_buffering off;
    }
}
NGXEOF

ln -sf /etc/nginx/sites-available/synkdr.com /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
echo "✅ Nginx configured"

# 6. SSL Certificate
certbot --nginx -d synkdr.com --non-interactive --agree-tos -m admin@synkdr.com 2>/dev/null || echo "⚠️ SSL: run manually: certbot --nginx -d synkdr.com"

# 7. Verify
sleep 3
echo ""
echo "═══════════════════════════════════════════════"
echo "  DEPLOYMENT COMPLETE"
echo "═══════════════════════════════════════════════"
systemctl status synkdr-bot --no-pager | head -5
echo ""
echo "🌐 Test: curl http://synkdr.com/"
curl -s http://synkdr.com/ | head -1
echo ""
echo "═══════════════════════════════════════════════"

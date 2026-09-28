/**
 * SynkDR Chat Widget
 * Self-contained embeddable chat widget.
 * 
 * Usage: <script src="https://synkdr.com/static/widget.js"></script>
 * 
 * SynkDR Engine v1 — Premium Glassmorphism UI
 */

(function () {
  'use strict';

  // ═══════════════════════════════════════════════════════════════
  // CONFIGURATION — Override via window.SYNKDR_CONFIG before loading
  // ═══════════════════════════════════════════════════════════════

  const DEFAULTS = {
    apiUrl: '',
    botName: 'Sofía',
    storeName: 'TrendyRD',
    greeting: '',
    placeholder: '',
    headerSubtitle: '',
    primaryColor: '#7C3AED',     // Violet-600
    primaryDark: '#6D28D9',      // Violet-700
    accentColor: '#A78BFA',      // Violet-400
    bgDark: '#0F0A1A',           // Deep dark purple
  };

  // Auto-detect API URL from script's own src when not explicitly configured
  function detectApiUrl() {
    const tag = document.querySelector('script[src*="widget.js"]');
    if (tag && tag.src) {
      try { return new URL(tag.src).origin; } catch (e) {}
    }
    return '';
  }

  const USER_CONFIG = window.SYNKDR_CONFIG || {};
  if (!USER_CONFIG.apiUrl) {
    DEFAULTS.apiUrl = detectApiUrl();
  }
  const CONFIG = {
    ...DEFAULTS,
    ...USER_CONFIG,
    greeting: USER_CONFIG.greeting || `¡Hola! 👋 Soy ${USER_CONFIG.botName || DEFAULTS.botName} de ${USER_CONFIG.storeName || DEFAULTS.storeName}.\n¿En qué puedo ayudarte hoy?`,
    placeholder: USER_CONFIG.placeholder || `Escríbele a ${USER_CONFIG.botName || DEFAULTS.botName}...`,
    headerSubtitle: USER_CONFIG.headerSubtitle || `Asistente de ${USER_CONFIG.storeName || DEFAULTS.storeName}`,
  };

  // ═══════════════════════════════════════════════════════════════
  // CUSTOMER ID (persistent across sessions)
  // ═══════════════════════════════════════════════════════════════

  function getCustomerId() {
    let id = localStorage.getItem('sofia_customer_id');
    if (!id) {
      id = 'web_' + Date.now().toString(36) + '_' + Math.random().toString(36).substr(2, 6);
      localStorage.setItem('sofia_customer_id', id);
    }
    return id;
  }

  // ═══════════════════════════════════════════════════════════════
  // INJECT STYLES
  // ═══════════════════════════════════════════════════════════════

  function injectStyles() {
    const style = document.createElement('style');
    style.id = 'synkdr-widget-styles';
    style.textContent = `
      /* ─── Google Font ─── */
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

      /* ─── Widget Container ─── */
      #synkdr-widget-container {
        position: fixed;
        bottom: 24px;
        right: 24px;
        z-index: 99999;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        font-size: 14px;
        line-height: 1.5;
      }

      /* ─── Chat Bubble Button ─── */
      #synkdr-bubble {
        width: 64px;
        height: 64px;
        border-radius: 50%;
        background: linear-gradient(135deg, ${CONFIG.primaryColor} 0%, ${CONFIG.primaryDark} 100%);
        border: none;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 8px 32px rgba(124, 58, 237, 0.4), 0 0 0 0 rgba(124, 58, 237, 0.3);
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        animation: synkdr-pulse 2s ease-in-out infinite;
        position: relative;
      }

      #synkdr-bubble:hover {
        transform: scale(1.1);
        box-shadow: 0 12px 40px rgba(124, 58, 237, 0.5);
      }

      #synkdr-bubble svg {
        width: 28px;
        height: 28px;
        fill: white;
        transition: transform 0.3s ease;
      }

      #synkdr-bubble.open svg.chat-icon { display: none; }
      #synkdr-bubble.open svg.close-icon { display: block; }
      #synkdr-bubble:not(.open) svg.chat-icon { display: block; }
      #synkdr-bubble:not(.open) svg.close-icon { display: none; }

      /* Notification dot */
      #synkdr-badge {
        position: absolute;
        top: -2px;
        right: -2px;
        width: 16px;
        height: 16px;
        background: #EF4444;
        border-radius: 50%;
        border: 2px solid white;
        display: block;
      }
      #synkdr-bubble.open #synkdr-badge { display: none; }
      .synkdr-badge-hidden { display: none !important; }

      @keyframes synkdr-pulse {
        0%, 100% { box-shadow: 0 8px 32px rgba(124, 58, 237, 0.4), 0 0 0 0 rgba(124, 58, 237, 0.3); }
        50% { box-shadow: 0 8px 32px rgba(124, 58, 237, 0.4), 0 0 0 12px rgba(124, 58, 237, 0); }
      }

      /* ─── Chat Window ─── */
      #synkdr-chat {
        position: absolute;
        bottom: 80px;
        right: 0;
        width: 380px;
        max-height: 560px;
        border-radius: 20px;
        overflow: hidden;
        display: none;
        flex-direction: column;
        background: rgba(15, 10, 26, 0.92);
        backdrop-filter: blur(20px) saturate(1.5);
        -webkit-backdrop-filter: blur(20px) saturate(1.5);
        border: 1px solid rgba(167, 139, 250, 0.15);
        box-shadow: 
          0 25px 60px rgba(0, 0, 0, 0.5),
          0 0 0 1px rgba(167, 139, 250, 0.1),
          inset 0 1px 0 rgba(255, 255, 255, 0.05);
        transform: translateY(16px) scale(0.95);
        opacity: 0;
        transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
      }

      #synkdr-chat.visible {
        display: flex;
        transform: translateY(0) scale(1);
        opacity: 1;
      }

      /* ─── Header ─── */
      #synkdr-header {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 16px 20px;
        background: linear-gradient(135deg, rgba(124, 58, 237, 0.3) 0%, rgba(109, 40, 217, 0.2) 100%);
        border-bottom: 1px solid rgba(167, 139, 250, 0.1);
      }

      #synkdr-avatar {
        width: 42px;
        height: 42px;
        border-radius: 50%;
        background: linear-gradient(135deg, ${CONFIG.primaryColor}, ${CONFIG.accentColor});
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 20px;
        flex-shrink: 0;
        box-shadow: 0 0 16px rgba(124, 58, 237, 0.4);
      }

      #synkdr-header-info h3 {
        margin: 0;
        font-size: 15px;
        font-weight: 600;
        color: #F5F3FF;
        letter-spacing: -0.01em;
      }

      #synkdr-header-info p {
        margin: 2px 0 0;
        font-size: 12px;
        color: ${CONFIG.accentColor};
        display: flex;
        align-items: center;
        gap: 5px;
      }

      #synkdr-header-info p::before {
        content: '';
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: #34D399;
        display: inline-block;
        animation: synkdr-online 2s ease-in-out infinite;
      }

      @keyframes synkdr-online {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.4; }
      }

      /* ─── Messages Area ─── */
      #synkdr-messages {
        flex: 1;
        overflow-y: auto;
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 12px;
        min-height: 300px;
        max-height: 380px;
        scroll-behavior: smooth;
      }

      #synkdr-messages::-webkit-scrollbar {
        width: 4px;
      }
      #synkdr-messages::-webkit-scrollbar-track {
        background: transparent;
      }
      #synkdr-messages::-webkit-scrollbar-thumb {
        background: rgba(167, 139, 250, 0.2);
        border-radius: 4px;
      }

      .synkdr-msg {
        max-width: 82%;
        padding: 10px 14px;
        border-radius: 16px;
        font-size: 13.5px;
        line-height: 1.5;
        animation: synkdr-fadeIn 0.3s ease;
        word-wrap: break-word;
      }

      .synkdr-msg.bot {
        align-self: flex-start;
        background: rgba(167, 139, 250, 0.12);
        border: 1px solid rgba(167, 139, 250, 0.08);
        color: #E8E0F5;
        border-bottom-left-radius: 6px;
      }

      .synkdr-msg.user {
        align-self: flex-end;
        background: linear-gradient(135deg, ${CONFIG.primaryColor}, ${CONFIG.primaryDark});
        color: white;
        border-bottom-right-radius: 6px;
      }

      .synkdr-msg .timestamp {
        display: block;
        font-size: 10px;
        opacity: 0.5;
        margin-top: 4px;
      }

      @keyframes synkdr-fadeIn {
        from { opacity: 0; transform: translateY(8px); }
        to { opacity: 1; transform: translateY(0); }
      }

      /* ─── Typing Indicator ─── */
      .synkdr-typing {
        align-self: flex-start;
        display: flex;
        gap: 4px;
        padding: 12px 18px;
        background: rgba(167, 139, 250, 0.12);
        border: 1px solid rgba(167, 139, 250, 0.08);
        border-radius: 16px;
        border-bottom-left-radius: 6px;
      }

      .synkdr-typing span {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: ${CONFIG.accentColor};
        animation: synkdr-dots 1.4s ease-in-out infinite;
      }
      .synkdr-typing span:nth-child(2) { animation-delay: 0.2s; }
      .synkdr-typing span:nth-child(3) { animation-delay: 0.4s; }

      @keyframes synkdr-dots {
        0%, 60%, 100% { opacity: 0.3; transform: scale(0.8); }
        30% { opacity: 1; transform: scale(1); }
      }

      /* ─── Input Area ─── */
      #synkdr-input-area {
        display: flex;
        gap: 8px;
        padding: 12px 16px;
        border-top: 1px solid rgba(167, 139, 250, 0.1);
        background: rgba(15, 10, 26, 0.6);
      }

      #synkdr-input {
        flex: 1;
        border: 1px solid rgba(167, 139, 250, 0.15);
        border-radius: 12px;
        padding: 10px 14px;
        background: rgba(255, 255, 255, 0.04);
        color: #F5F3FF;
        font-family: inherit;
        font-size: 13.5px;
        outline: none;
        transition: border-color 0.2s;
        resize: none;
        max-height: 60px;
      }

      #synkdr-input::placeholder {
        color: rgba(167, 139, 250, 0.4);
      }

      #synkdr-input:focus {
        border-color: ${CONFIG.accentColor};
        box-shadow: 0 0 0 3px rgba(167, 139, 250, 0.1);
      }

      #synkdr-send {
        width: 40px;
        height: 40px;
        border-radius: 12px;
        border: none;
        background: linear-gradient(135deg, ${CONFIG.primaryColor}, ${CONFIG.primaryDark});
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.2s;
        flex-shrink: 0;
        align-self: flex-end;
      }

      #synkdr-send:hover {
        transform: scale(1.05);
        box-shadow: 0 4px 16px rgba(124, 58, 237, 0.4);
      }

      #synkdr-send:disabled {
        opacity: 0.5;
        cursor: not-allowed;
        transform: none;
      }

      #synkdr-send svg {
        width: 18px;
        height: 18px;
        fill: white;
      }

      /* ─── Powered By ─── */
      #synkdr-powered {
        text-align: center;
        padding: 6px;
        font-size: 10px;
        color: rgba(167, 139, 250, 0.25);
        letter-spacing: 0.02em;
      }

      /* ─── Mobile Responsive ─── */
      @media (max-width: 480px) {
        #synkdr-widget-container {
          bottom: 16px;
          right: 16px;
        }
        #synkdr-chat {
          width: calc(100vw - 32px);
          max-height: calc(100vh - 120px);
          right: 0;
          bottom: 76px;
        }
        #synkdr-bubble {
          width: 56px;
          height: 56px;
        }
      }
    `;
    document.head.appendChild(style);
  }

  // ═══════════════════════════════════════════════════════════════
  // BUILD DOM
  // ═══════════════════════════════════════════════════════════════

  function buildWidget() {
    const container = document.createElement('div');
    container.id = 'synkdr-widget-container';
    container.innerHTML = `
      <!-- Chat Window -->
      <div id="synkdr-chat">
        <div id="synkdr-header">
          <div id="synkdr-avatar">👩🏽</div>
          <div id="synkdr-header-info">
            <h3>${CONFIG.botName}</h3>
            <p>En línea</p>
          </div>
        </div>
        <div id="synkdr-messages"></div>
        <div id="synkdr-input-area">
          <input type="text" id="synkdr-input" placeholder="${CONFIG.placeholder}" autocomplete="off" />
          <button id="synkdr-send" aria-label="Enviar">
            <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
          </button>
        </div>
        <div id="synkdr-powered">Powered by Sofía AI ✨</div>
      </div>

      <!-- Floating Bubble -->
      <button id="synkdr-bubble" aria-label="Chat con Sofía">
        <span id="synkdr-badge"></span>
        <svg class="chat-icon" viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z"/></svg>
        <svg class="close-icon" viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
      </button>
    `;
    document.body.appendChild(container);
  }

  // ═══════════════════════════════════════════════════════════════
  // CHAT LOGIC
  // ═══════════════════════════════════════════════════════════════

  let isOpen = false;
  let isWaiting = false;
  let hasGreeted = false;

  function toggleChat() {
    const chat = document.getElementById('synkdr-chat');
    const bubble = document.getElementById('synkdr-bubble');
    const badge = document.getElementById('synkdr-badge');

    isOpen = !isOpen;

    if (isOpen) {
      chat.style.display = 'flex';
      bubble.classList.add('open');
      badge.classList.add('synkdr-badge-hidden');

      // Trigger reflow for animation
      requestAnimationFrame(() => {
        chat.classList.add('visible');
      });

      // Show greeting on first open
      if (!hasGreeted) {
        hasGreeted = true;
        addMessage(CONFIG.greeting, 'bot');
      }

      // Focus input
      setTimeout(() => {
        document.getElementById('synkdr-input').focus();
      }, 350);

    } else {
      chat.classList.remove('visible');
      bubble.classList.remove('open');
      setTimeout(() => {
        chat.style.display = 'none';
      }, 350);
    }
  }

  function addMessage(text, sender) {
    const messages = document.getElementById('synkdr-messages');
    const now = new Date();
    const time = now.toLocaleTimeString('es-DO', { hour: '2-digit', minute: '2-digit' });

    const msg = document.createElement('div');
    msg.className = `synkdr-msg ${sender}`;

    // Convert newlines to <br>
    const formattedText = text.replace(/\n/g, '<br>');
    msg.innerHTML = `${formattedText}<span class="timestamp">${time}</span>`;

    messages.appendChild(msg);
    messages.scrollTop = messages.scrollHeight;
  }

  function showTyping() {
    const messages = document.getElementById('synkdr-messages');
    const typing = document.createElement('div');
    typing.className = 'synkdr-typing';
    typing.id = 'synkdr-typing-indicator';
    typing.innerHTML = '<span></span><span></span><span></span>';
    messages.appendChild(typing);
    messages.scrollTop = messages.scrollHeight;
  }

  function hideTyping() {
    const typing = document.getElementById('synkdr-typing-indicator');
    if (typing) typing.remove();
  }

  async function sendMessage() {
    const input = document.getElementById('synkdr-input');
    const sendBtn = document.getElementById('synkdr-send');
    const text = input.value.trim();

    if (!text || isWaiting) return;

    // Show user message
    addMessage(text, 'user');
    input.value = '';

    // Disable input while waiting
    isWaiting = true;
    sendBtn.disabled = true;
    showTyping();

    try {
      const response = await fetch(`${CONFIG.apiUrl}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          customer_id: getCustomerId(),
          message: text,
          channel: 'webchat',
        }),
      });

      hideTyping();

      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const data = await response.json();
      addMessage(data.response, 'bot');

    } catch (error) {
      hideTyping();
      console.error('Sofía Widget Error:', error);
      addMessage('Ups, tuve un problemita de conexión. ¿Puedes intentar otra vez? 🙏', 'bot');
    }

    isWaiting = false;
    sendBtn.disabled = false;
    input.focus();
  }

  // ═══════════════════════════════════════════════════════════════
  // EVENT LISTENERS
  // ═══════════════════════════════════════════════════════════════

  function attachEvents() {
    // Toggle chat
    document.getElementById('synkdr-bubble').addEventListener('click', toggleChat);

    // Send on click
    document.getElementById('synkdr-send').addEventListener('click', sendMessage);

    // Send on Enter
    document.getElementById('synkdr-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
  }

  // ═══════════════════════════════════════════════════════════════
  // INITIALIZE
  // ═══════════════════════════════════════════════════════════════

  function init() {
    // Don't double-initialize
    if (document.getElementById('synkdr-widget-container')) return;

    injectStyles();
    buildWidget();
    attachEvents();

    console.log(`✅ Sofía Widget loaded (${CONFIG.storeName})`);
  }

  // Start when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();

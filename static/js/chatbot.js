/**
 * NutriCheck — AI Diet Chatbot (RAG)
 * Handles chat UI, message sending, and rendering responses.
 */

(function () {
    'use strict';

    // ── State ──────────────────────────────────────────────
    let isOpen       = false;
    let isTyping     = false;
    let currentAnalysis = null;  // Set by dashboard.js after a scan

    // ── DOM ────────────────────────────────────────────────
    let panel, messagesEl, inputEl, sendBtn, badge;

    function init() {
        panel      = document.getElementById('chatPanel');
        messagesEl = document.getElementById('chatMessages');
        inputEl    = document.getElementById('chatInput');
        sendBtn    = document.getElementById('chatSendBtn');
        badge      = document.getElementById('chatBadge');

        const openBtn  = document.getElementById('chatOpenBtn');
        const closeBtn = document.getElementById('chatCloseBtn');
        const clearBtn = document.getElementById('chatClearBtn');

        if (!panel || !openBtn) return;

        openBtn.addEventListener('click', togglePanel);
        closeBtn.addEventListener('click', closePanel);
        clearBtn.addEventListener('click', clearChat);
        sendBtn.addEventListener('click', sendMessage);

        inputEl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        // Auto-resize textarea
        inputEl.addEventListener('input', () => {
            inputEl.style.height = 'auto';
            inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
        });

        // Greeting message
        appendBotMessage(
            "👋 Hi! I'm **NutriBot**, your AI diet assistant. I can answer questions about nutrition, food labels, diet tips, and more.\n\n" +
            "Try asking:\n• *Is this product good for weight loss?*\n• *How much sugar per day is safe?*\n• *What's a high-fiber snack?*"
        );
    }

    // ── Panel Controls ─────────────────────────────────────
    function togglePanel() {
        isOpen ? closePanel() : openPanel();
    }

    function openPanel() {
        isOpen = true;
        panel.classList.add('open');
        if (badge) badge.style.display = 'none';
        setTimeout(() => inputEl && inputEl.focus(), 300);
    }

    function closePanel() {
        isOpen = false;
        panel.classList.remove('open');
    }

    function clearChat() {
        if (!messagesEl) return;
        messagesEl.innerHTML = '';
        appendBotMessage("Chat cleared! Ask me anything about nutrition or diet. 🌿");
    }

    // ── Message Sending ────────────────────────────────────
    async function sendMessage() {
        const text = inputEl.value.trim();
        if (!text || isTyping) return;

        appendUserMessage(text);
        inputEl.value = '';
        inputEl.style.height = 'auto';

        showTyping();

        try {
            const payload = {
                message: text,
                analysis_context: currentAnalysis || null,
            };

            const res = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });

            const data = await res.json();
            hideTyping();

            if (res.ok) {
                appendBotMessage(data.reply);
            } else {
                appendBotMessage('⚠️ ' + (data.error || 'Something went wrong. Please try again.'));
            }
        } catch (err) {
            hideTyping();
            appendBotMessage('⚠️ Network error. Please check your connection.');
        }
    }

    // ── Message Rendering ──────────────────────────────────
    function appendUserMessage(text) {
        const div = document.createElement('div');
        div.className = 'chat-msg chat-msg-user';
        div.innerHTML = `<div class="chat-bubble chat-bubble-user">${escapeHtml(text)}</div>`;
        messagesEl.appendChild(div);
        scrollToBottom();
    }

    function appendBotMessage(text) {
        const div = document.createElement('div');
        div.className = 'chat-msg chat-msg-bot';
        div.innerHTML = `
            <div class="chat-avatar">🤖</div>
            <div class="chat-bubble chat-bubble-bot">${renderMarkdown(text)}</div>
        `;
        messagesEl.appendChild(div);
        scrollToBottom();
    }

    function showTyping() {
        isTyping = true;
        sendBtn.disabled = true;
        const div = document.createElement('div');
        div.className = 'chat-msg chat-msg-bot';
        div.id = 'typingIndicator';
        div.innerHTML = `
            <div class="chat-avatar">🤖</div>
            <div class="chat-bubble chat-bubble-bot chat-typing">
                <span></span><span></span><span></span>
            </div>
        `;
        messagesEl.appendChild(div);
        scrollToBottom();
    }

    function hideTyping() {
        isTyping = false;
        sendBtn.disabled = false;
        const el = document.getElementById('typingIndicator');
        if (el) el.remove();
    }

    function scrollToBottom() {
        if (messagesEl) {
            messagesEl.scrollTop = messagesEl.scrollHeight;
        }
    }

    // ── Utilities ──────────────────────────────────────────
    function escapeHtml(text) {
        return text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    /**
     * Very lightweight markdown renderer (bold, italic, code, bullet lists, newlines).
     * No full markdown parser needed for a chat context.
     */
    function renderMarkdown(text) {
        return text
            // Escape HTML first
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            // Bold **text**
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            // Italic *text*
            .replace(/\*(.+?)\*/g, '<em>$1</em>')
            // Inline code `code`
            .replace(/`(.+?)`/g, '<code>$1</code>')
            // Bullet list lines starting with •
            .replace(/^• (.+)$/gm, '<li>$1</li>')
            // Wrap consecutive <li> in <ul>
            .replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>')
            // Newlines → <br>
            .replace(/\n/g, '<br>');
    }

    // ── Public API (called by dashboard.js) ────────────────
    window.NutriChat = {
        setAnalysisContext(analysis) {
            currentAnalysis = analysis;
            // Show badge to hint user they can ask about the scanned product
            if (badge && !isOpen) {
                badge.style.display = 'flex';
                badge.textContent = '1';
            }
        },
        open: openPanel,
        close: closePanel,
    };

    // ── Init ───────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', init);
})();

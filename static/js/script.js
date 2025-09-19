document.addEventListener('DOMContentLoaded', () => {
    const chatWindow = document.getElementById('chat-window');
    const chatForm = document.getElementById('chat-form');
    const messageInput = document.getElementById('message-input');
    const sendButton = document.getElementById('send-button');
    const typingIndicator = document.getElementById('typing-indicator');
    const faqSidebar = document.getElementById('faq-sidebar');
    const faqToggle = document.getElementById('faq-toggle');
    const faqList = document.getElementById('faq-list');

    let sessionId = null;
    const API_BASE_URL = 'http://localhost:8000/api/v1';

    // --- Core Functions ---

    /**
     * Starts a new chat session
     */
    async function startSession() {
        try {
            showTypingIndicator();
            const response = await fetch(`${API_BASE_URL}/session/start`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            sessionId = data.session_id;
            addMessage('bot', data.response_to_user);
        } catch (error) {
            console.error('Error starting session:', error);
            addMessage('bot', 'Sorry, I am having trouble connecting. Please try again later.');
        } finally {
            hideTypingIndicator();
        }
    }

    /**
     * Sends a message to the backend
     * @param {string} message - The user's message
     */
    async function sendMessage(message) {
        if (!sessionId) {
            addMessage('bot', 'The session is not active. Please refresh the page.');
            return;
        }

        try {
            showTypingIndicator();
            const response = await fetch(`${API_BASE_URL}/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message, session_id: sessionId }),
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            addMessage('bot', data.response_to_user);
        } catch (error) {
            console.error('Error sending message:', error);
            addMessage('bot', 'An error occurred. Please try again.');
        } finally {
            hideTypingIndicator();
        }
    }

    // --- UI Helper Functions ---

    /**
     * Adds a message to the chat window
     * @param {'user' | 'bot'} sender - The sender of the message
     * @param {string} text - The message content
     */
    function addMessage(sender, text) {
        const messageElement = document.createElement('div');
        messageElement.classList.add('message', sender);

        const icon = document.createElement('div');
        icon.classList.add('icon');
        icon.innerHTML = sender === 'bot' ? '<i class="fas fa-robot"></i>' : '<i class="fas fa-user"></i>';

        const messageText = document.createElement('div');
        messageText.classList.add('text');
        messageText.textContent = text;

        const timestamp = document.createElement('div');
        timestamp.classList.add('timestamp');
        timestamp.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

        messageElement.appendChild(icon);
        messageElement.appendChild(messageText);
        messageText.appendChild(timestamp);
        
        chatWindow.appendChild(messageElement);
        scrollToBottom();
    }

    /**
     * Scrolls the chat window to the bottom
     */
    function scrollToBottom() {
        chatWindow.scrollTop = chatWindow.scrollHeight;
    }

    /**
     * Shows the typing indicator
     */
    function showTypingIndicator() {
        typingIndicator.style.display = 'flex';
        sendButton.disabled = true;
        messageInput.disabled = true;
    }

    /**
     * Hides the typing indicator
     */
    function hideTypingIndicator() {
        typingIndicator.style.display = 'none';
        sendButton.disabled = false;
        messageInput.disabled = false;
        messageInput.focus();
    }

    function closeSidebar() {
        faqSidebar.classList.remove('open');
        if (window.innerWidth > 800) {
            document.body.classList.remove('sidebar-open');
        }
    }

    // --- Event Listeners ---

    chatForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const message = messageInput.value.trim();
        if (message) {
            addMessage('user', message);
            sendMessage(message);
            messageInput.value = '';
        }
    });

    faqToggle.addEventListener('click', () => {
        faqSidebar.classList.toggle('open');
        if (window.innerWidth > 800) {
            document.body.classList.toggle('sidebar-open');
        }
    });

    faqList.addEventListener('click', (e) => {
        if (e.target && e.target.classList.contains('faq-item')) {
            const question = e.target.textContent;
            addMessage('user', question);
            sendMessage(question);
            closeSidebar();
        }
    });

    // Close sidebar if clicking outside of it
    document.addEventListener('click', (e) => {
        if (faqSidebar.classList.contains('open') && !faqSidebar.contains(e.target) && !faqToggle.contains(e.target)) {
            closeSidebar();
        }
    });


    // --- Initialization ---
    startSession();
});
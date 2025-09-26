document.addEventListener('DOMContentLoaded', () => {
    const chatWindow = document.getElementById('chat-window');
    const chatForm = document.getElementById('chat-form');
    const messageInput = document.getElementById('message-input');
    const sendButton = document.getElementById('send-button');
    const typingIndicator = document.getElementById('typing-indicator');
    const sidebar = document.getElementById('sidebar');
    const sidebarToggle = document.getElementById('sidebar-toggle');
    const sidebarOverlay = document.getElementById('sidebar-overlay');
    const faqList = document.getElementById('faq-list');
    const loadingScreen = document.getElementById('loading-screen');
    const themeToggle = document.getElementById('theme-toggle');
    const themeIcon = document.getElementById('theme-icon');

    let sessionId = null;
    const API_BASE_URL = 'http://localhost:8000/api/v1';

    // Initialize MarkdownIt
    let md;
    if (window.markdownit) {
        md = window.markdownit({
            html: true,
            linkify: true,
            typographer: true,
            breaks: true
        });
        console.log('Markdown-it initialized successfully');
    } else {
        console.error('Markdown-it library not loaded!');
        // Fallback function
        md = {
            render: function(text) {
                return text.replace(/\n/g, '<br>');
            }
        };
    }

    // Theme functionality
    function initTheme() {
        const savedTheme = localStorage.getItem('theme') || 'light';
        document.documentElement.setAttribute('data-theme', savedTheme);
        updateThemeIcon(savedTheme);
    }

    function toggleTheme() {
        const currentTheme = document.documentElement.getAttribute('data-theme');
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        
        document.documentElement.setAttribute('data-theme', newTheme);
        localStorage.setItem('theme', newTheme);
        updateThemeIcon(newTheme);
    }

    function updateThemeIcon(theme) {
        themeIcon.className = theme === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
    }

    // Show loading screen initially
    function showLoadingScreen() {
        loadingScreen.style.display = 'flex';
        loadingScreen.classList.remove('fade-out');
    }

    function hideLoadingScreen() {
        loadingScreen.classList.add('fade-out');
        setTimeout(() => {
            loadingScreen.style.display = 'none';
        }, 500);
    }

    // Sidebar functionality
    function toggleSidebar() {
        const isMobile = window.innerWidth <= 768;
        
        if (isMobile) {
            sidebar.classList.toggle('open');
            sidebarOverlay.classList.toggle('active');
        } else {
            sidebar.classList.toggle('collapsed');
        }
    }

    function closeSidebar() {
        const isMobile = window.innerWidth <= 768;
        
        if (isMobile) {
            sidebar.classList.remove('open');
            sidebarOverlay.classList.remove('active');
        }
    }

    // Auto-resize textarea
    function autoResizeTextarea() {
        messageInput.style.height = 'auto';
        messageInput.style.height = Math.min(messageInput.scrollHeight, 120) + 'px';
    }

    // --- Core Functions ---

    /**
     * Starts a new chat session
     */
    async function startSession() {
        try {
            // Simulate loading time
            await new Promise(resolve => setTimeout(resolve, 2000));
            
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
            
            // Hide loading screen before showing the greeting
            hideLoadingScreen();
            
            // Add a slight delay before showing the greeting
            setTimeout(() => {
                addMessage('bot', data.response_to_user);
            }, 300);
            
        } catch (error) {
            console.error('Error starting session:', error);
            hideLoadingScreen();
            setTimeout(() => {
                addMessage('bot', 'Sorry, I am having trouble connecting. Please try again later.');
            }, 300);
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
        
        // Use markdown-it to render markdown for bot messages
        if (sender === 'bot') {
            console.log('Raw text:', text);
            const renderedHTML = md.render(text);
            console.log('Rendered HTML:', renderedHTML);
            messageText.innerHTML = renderedHTML;
        } else {
            messageText.textContent = text;
        }

        const timestamp = document.createElement('div');
        timestamp.classList.add('timestamp');
        timestamp.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

        messageElement.appendChild(icon);
        messageElement.appendChild(messageText);
        messageText.appendChild(timestamp);
        
        chatWindow.appendChild(messageElement);
        scrollToBottom();
    }

    function formatText(text) {
        // Use MarkdownIt to render markdown
        return md.render(text);
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

    // Event Listeners
    chatForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const message = messageInput.value.trim();
        if (message) {
            addMessage('user', message);
            sendMessage(message);
            messageInput.value = '';
            autoResizeTextarea();
        }
    });

    messageInput.addEventListener('input', autoResizeTextarea);
    
    messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            chatForm.dispatchEvent(new Event('submit'));
        }
    });

    sidebarToggle.addEventListener('click', toggleSidebar);
    
    sidebarOverlay.addEventListener('click', closeSidebar);

    themeToggle.addEventListener('click', toggleTheme);

    faqList.addEventListener('click', (e) => {
        if (e.target && e.target.classList.contains('faq-item')) {
            const question = e.target.textContent;
            addMessage('user', question);
            sendMessage(question);
            closeSidebar();
        }
    });

    // Handle window resize
    window.addEventListener('resize', () => {
        const isMobile = window.innerWidth <= 768;
        if (!isMobile) {
            sidebar.classList.remove('open');
            sidebarOverlay.classList.remove('active');
        }
    });


    // --- Initialization ---
    initTheme();
    showLoadingScreen();
    startSession();
});
/**
 * aria_ui.tsx — Interfaz de Usuario Completa para ARIA
 * 
 * Componentes principales:
 * - Chat interactivo
 * - Editor de código con syntax highlighting
 * - Terminal en tiempo real
 * - Explorador de archivos
 * - Gestor de tareas
 */

import React, { useState, useRef, useEffect } from 'react';
import { Terminal, Code, FileExplorer, Chat, TaskManager } from './components';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  code?: string;
  output?: string;
}

interface EditorState {
  language: string;
  code: string;
  filename: string;
}

interface TerminalState {
  history: string[];
  currentInput: string;
  isExecuting: boolean;
}

export const AriaUI: React.FC = () => {
  // Chat state
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  // Editor state
  const [editorState, setEditorState] = useState<EditorState>({
    language: 'python',
    code: '',
    filename: 'untitled.py',
  });

  // Terminal state
  const [terminalState, setTerminalState] = useState<TerminalState>({
    history: [],
    currentInput: '',
    isExecuting: false,
  });

  // File explorer state
  const [currentDirectory, setCurrentDirectory] = useState('/');
  const [files, setFiles] = useState<any[]>([]);

  // Task state
  const [tasks, setTasks] = useState<any[]>([]);
  const [activeTab, setActiveTab] = useState<'chat' | 'editor' | 'terminal' | 'files'>('chat');

  const chatEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Handle sending messages
  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!inputValue.trim()) return;

    // Add user message
    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: inputValue,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputValue('');
    setIsLoading(true);

    try {
      // Send to backend
      const response = await fetch('/api/aria/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: inputValue,
          context: {
            editor: editorState,
            terminal: terminalState,
          },
        }),
      });

      const data = await response.json();

      // Add assistant response
      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: data.response,
        timestamp: new Date(),
        code: data.code,
        output: data.output,
      };

      setMessages((prev) => [...prev, assistantMessage]);

      // Update editor if code was generated
      if (data.code) {
        setEditorState((prev) => ({
          ...prev,
          code: data.code,
        }));
      }
    } catch (error) {
      console.error('Error sending message:', error);
      const errorMessage: Message = {
        id: (Date.now() + 2).toString(),
        role: 'assistant',
        content: 'Error procesando tu solicitud',
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  // Handle code execution
  const handleExecuteCode = async () => {
    setTerminalState((prev) => ({
      ...prev,
      isExecuting: true,
    }));

    try {
      const response = await fetch('/api/aria/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          code: editorState.code,
          language: editorState.language,
        }),
      });

      const data = await response.json();

      setTerminalState((prev) => ({
        ...prev,
        history: [
          ...prev.history,
          `$ ${editorState.language} ${editorState.filename}`,
          data.output || data.error,
        ],
        isExecuting: false,
      }));
    } catch (error) {
      console.error('Error executing code:', error);
      setTerminalState((prev) => ({
        ...prev,
        history: [...prev.history, 'Error ejecutando código'],
        isExecuting: false,
      }));
    }
  };

  // Handle terminal input
  const handleTerminalInput = async (command: string) => {
    setTerminalState((prev) => ({
      ...prev,
      history: [...prev.history, `$ ${command}`],
      isExecuting: true,
    }));

    try {
      const response = await fetch('/api/aria/shell', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command }),
      });

      const data = await response.json();

      setTerminalState((prev) => ({
        ...prev,
        history: [...prev.history, data.output || data.error],
        isExecuting: false,
      }));
    } catch (error) {
      console.error('Error executing command:', error);
      setTerminalState((prev) => ({
        ...prev,
        history: [...prev.history, 'Error ejecutando comando'],
        isExecuting: false,
      }));
    }
  };

  // Handle file operations
  const handleListFiles = async (directory: string) => {
    try {
      const response = await fetch(`/api/aria/files?directory=${directory}`);
      const data = await response.json();
      setFiles(data.files || []);
      setCurrentDirectory(directory);
    } catch (error) {
      console.error('Error listing files:', error);
    }
  };

  return (
    <div className="aria-ui">
      <header className="aria-header">
        <h1>🚀 ARIA — Autonomous Reasoning Intelligence Agent</h1>
        <div className="header-info">
          <span className="status">Status: Online</span>
          <span className="version">v1.0.0</span>
        </div>
      </header>

      <div className="aria-container">
        {/* Sidebar Navigation */}
        <nav className="aria-sidebar">
          <div className="nav-section">
            <h3>Workspace</h3>
            <button
              className={`nav-item ${activeTab === 'chat' ? 'active' : ''}`}
              onClick={() => setActiveTab('chat')}
            >
              💬 Chat
            </button>
            <button
              className={`nav-item ${activeTab === 'editor' ? 'active' : ''}`}
              onClick={() => setActiveTab('editor')}
            >
              📝 Editor
            </button>
            <button
              className={`nav-item ${activeTab === 'terminal' ? 'active' : ''}`}
              onClick={() => setActiveTab('terminal')}
            >
              ⌨️ Terminal
            </button>
            <button
              className={`nav-item ${activeTab === 'files' ? 'active' : ''}`}
              onClick={() => setActiveTab('files')}
            >
              📁 Files
            </button>
          </div>

          <div className="nav-section">
            <h3>Tasks</h3>
            <div className="task-list">
              {tasks.map((task) => (
                <div key={task.id} className="task-item">
                  <span className={`task-status ${task.status}`}></span>
                  {task.name}
                </div>
              ))}
            </div>
          </div>
        </nav>

        {/* Main Content Area */}
        <main className="aria-main">
          {activeTab === 'chat' && (
            <div className="chat-container">
              <div className="messages">
                {messages.map((msg) => (
                  <div key={msg.id} className={`message ${msg.role}`}>
                    <div className="message-avatar">
                      {msg.role === 'user' ? '👤' : '🤖'}
                    </div>
                    <div className="message-content">
                      <p>{msg.content}</p>
                      {msg.code && (
                        <pre className="message-code">
                          <code>{msg.code}</code>
                        </pre>
                      )}
                      {msg.output && (
                        <pre className="message-output">
                          <code>{msg.output}</code>
                        </pre>
                      )}
                    </div>
                  </div>
                ))}
                {isLoading && (
                  <div className="message assistant">
                    <div className="message-avatar">🤖</div>
                    <div className="message-content">
                      <div className="typing-indicator">
                        <span></span>
                        <span></span>
                        <span></span>
                      </div>
                    </div>
                  </div>
                )}
                <div ref={chatEndRef} />
              </div>

              <form className="chat-input-form" onSubmit={handleSendMessage}>
                <input
                  type="text"
                  value={inputValue}\n                  onChange={(e) => setInputValue(e.target.value)}\n                  placeholder="Escribe tu solicitud aquí..."\n                  disabled={isLoading}\n                />\n                <button type="submit" disabled={isLoading}>\n                  Enviar\n                </button>\n              </form>\n            </div>\n          )}\n\n          {activeTab === 'editor' && (\n            <div className=\"editor-container\">\n              <div className=\"editor-toolbar\">\n                <select\n                  value={editorState.language}\n                  onChange={(e) =>\n                    setEditorState((prev) => ({\n                      ...prev,\n                      language: e.target.value,\n                    }))\n                  }\n                >\n                  <option value=\"python\">Python</option>\n                  <option value=\"javascript\">JavaScript</option>\n                  <option value=\"go\">Go</option>\n                  <option value=\"rust\">Rust</option>\n                  <option value=\"java\">Java</option>\n                </select>\n                <input\n                  type=\"text\"\n                  value={editorState.filename}\n                  onChange={(e) =>\n                    setEditorState((prev) => ({\n                      ...prev,\n                      filename: e.target.value,\n                    }))\n                  }\n                  placeholder=\"Nombre del archivo\"\n                />\n                <button onClick={handleExecuteCode}>▶️ Ejecutar</button>\n              </div>\n\n              <textarea\n                className=\"code-editor\"\n                value={editorState.code}\n                onChange={(e) =>\n                  setEditorState((prev) => ({\n                    ...prev,\n                    code: e.target.value,\n                  }))\n                }\n                placeholder=\"Escribe tu código aquí...\"\n              />\n            </div>\n          )}\n\n          {activeTab === 'terminal' && (\n            <Terminal\n              history={terminalState.history}\n              onInput={handleTerminalInput}\n              isExecuting={terminalState.isExecuting}\n            />\n          )}\n\n          {activeTab === 'files' && (\n            <FileExplorer\n              currentDirectory={currentDirectory}\n              files={files}\n              onNavigate={handleListFiles}\n            />\n          )}\n        </main>\n      </div>\n\n      <style jsx>{`\n        .aria-ui {\n          display: flex;\n          flex-direction: column;\n          height: 100vh;\n          background: #0d1117;\n          color: #c9d1d9;\n          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;\n        }\n\n        .aria-header {\n          background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);\n          padding: 1.5rem;\n          color: white;\n          display: flex;\n          justify-content: space-between;\n          align-items: center;\n          box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);\n        }\n\n        .aria-header h1 {\n          margin: 0;\n          font-size: 1.5rem;\n        }\n\n        .header-info {\n          display: flex;\n          gap: 1rem;\n          font-size: 0.9rem;\n        }\n\n        .aria-container {\n          display: flex;\n          flex: 1;\n          overflow: hidden;\n        }\n\n        .aria-sidebar {\n          width: 250px;\n          background: #161b22;\n          border-right: 1px solid #30363d;\n          overflow-y: auto;\n          padding: 1rem;\n        }\n\n        .nav-section {\n          margin-bottom: 2rem;\n        }\n\n        .nav-section h3 {\n          font-size: 0.85rem;\n          text-transform: uppercase;\n          color: #8b949e;\n          margin: 0 0 0.5rem 0;\n          padding: 0 0.5rem;\n        }\n\n        .nav-item {\n          display: block;\n          width: 100%;\n          padding: 0.75rem;\n          background: none;\n          border: none;\n          color: #c9d1d9;\n          text-align: left;\n          cursor: pointer;\n          border-radius: 4px;\n          transition: background 0.2s;\n        }\n\n        .nav-item:hover {\n          background: #30363d;\n        }\n\n        .nav-item.active {\n          background: #667eea;\n          color: white;\n        }\n\n        .aria-main {\n          flex: 1;\n          display: flex;\n          flex-direction: column;\n          overflow: hidden;\n        }\n\n        .chat-container {\n          display: flex;\n          flex-direction: column;\n          height: 100%;\n        }\n\n        .messages {\n          flex: 1;\n          overflow-y: auto;\n          padding: 1rem;\n          display: flex;\n          flex-direction: column;\n          gap: 1rem;\n        }\n\n        .message {\n          display: flex;\n          gap: 1rem;\n          animation: slideIn 0.3s ease-out;\n        }\n\n        @keyframes slideIn {\n          from {\n            opacity: 0;\n            transform: translateY(10px);\n          }\n          to {\n            opacity: 1;\n            transform: translateY(0);\n          }\n        }\n\n        .message-avatar {\n          font-size: 1.5rem;\n          flex-shrink: 0;\n        }\n\n        .message-content {\n          flex: 1;\n          background: #161b22;\n          padding: 1rem;\n          border-radius: 8px;\n          border-left: 3px solid #667eea;\n        }\n\n        .message.user .message-content {\n          background: #238636;\n          border-left-color: #238636;\n        }\n\n        .message-code {\n          background: #0d1117;\n          padding: 0.5rem;\n          border-radius: 4px;\n          overflow-x: auto;\n          margin-top: 0.5rem;\n        }\n\n        .chat-input-form {\n          display: flex;\n          gap: 0.5rem;\n          padding: 1rem;\n          border-top: 1px solid #30363d;\n        }\n\n        .chat-input-form input {\n          flex: 1;\n          padding: 0.75rem;\n          background: #0d1117;\n          border: 1px solid #30363d;\n          color: #c9d1d9;\n          border-radius: 4px;\n        }\n\n        .chat-input-form button {\n          padding: 0.75rem 1.5rem;\n          background: #667eea;\n          color: white;\n          border: none;\n          border-radius: 4px;\n          cursor: pointer;\n          font-weight: 600;\n        }\n\n        .editor-container {\n          display: flex;\n          flex-direction: column;\n          height: 100%;\n        }\n\n        .editor-toolbar {\n          display: flex;\n          gap: 0.5rem;\n          padding: 1rem;\n          border-bottom: 1px solid #30363d;\n          background: #161b22;\n        }\n\n        .editor-toolbar select,\n        .editor-toolbar input {\n          padding: 0.5rem;\n          background: #0d1117;\n          border: 1px solid #30363d;\n          color: #c9d1d9;\n          border-radius: 4px;\n        }\n\n        .code-editor {\n          flex: 1;\n          padding: 1rem;\n          background: #0d1117;\n          color: #c9d1d9;\n          border: none;\n          font-family: 'Courier New', monospace;\n          font-size: 0.9rem;\n          resize: none;\n        }\n\n        .typing-indicator {\n          display: flex;\n          gap: 0.25rem;\n        }\n\n        .typing-indicator span {\n          width: 0.5rem;\n          height: 0.5rem;\n          background: #667eea;\n          border-radius: 50%;\n          animation: pulse 1.4s infinite;\n        }\n\n        .typing-indicator span:nth-child(2) {\n          animation-delay: 0.2s;\n        }\n\n        .typing-indicator span:nth-child(3) {\n          animation-delay: 0.4s;\n        }\n\n        @keyframes pulse {\n          0%, 60%, 100% {\n            opacity: 0.3;\n          }\n          30% {\n            opacity: 1;\n          }\n        }\n      `}</style>\n    </div>\n  );\n};\n\nexport default AriaUI;\n

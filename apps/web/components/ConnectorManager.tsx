/**
 * ConnectorManager.tsx — Gestor de Conectores MCP y Zapier
 * 
 * Permite:
 * - Conectar servidores MCP
 * - Configurar Zapier
 * - Descubrir herramientas disponibles
 */

import React, { useState, useEffect } from 'react';

interface Connector {
  id: string;
  name: string;
  type: 'mcp' | 'zapier' | 'api';
  status: 'connected' | 'disconnected' | 'error';
  tools?: string[];
  config?: Record<string, any>;
}

interface Tool {
  name: string;
  description: string;
  inputSchema?: Record<string, any>;
}

export const ConnectorManager: React.FC = () => {
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [selectedConnector, setSelectedConnector] = useState<Connector | null>(null);
  const [tools, setTools] = useState<Tool[]>([]);
  const [showAddForm, setShowAddForm] = useState(false);
  const [formData, setFormData] = useState({
    name: '',
    type: 'mcp' as const,
    url: '',
    apiKey: '',
  });

  useEffect(() => {
    loadConnectors();
  }, []);

  const loadConnectors = async () => {
    try {
      const response = await fetch('/api/aria/connectors');
      const data = await response.json();
      setConnectors(data.connectors || []);
    } catch (error) {
      console.error('Error loading connectors:', error);
    }
  };

  const handleAddConnector = async (e: React.FormEvent) => {
    e.preventDefault();

    try {
      const response = await fetch('/api/aria/connectors', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });

      const data = await response.json();

      if (data.success) {
        setConnectors((prev) => [...prev, data.connector]);
        setFormData({ name: '', type: 'mcp', url: '', apiKey: '' });
        setShowAddForm(false);
      }
    } catch (error) {
      console.error('Error adding connector:', error);
    }
  };

  const handleSelectConnector = async (connector: Connector) => {
    setSelectedConnector(connector);

    try {
      const response = await fetch(`/api/aria/connectors/${connector.id}/tools`);
      const data = await response.json();
      setTools(data.tools || []);
    } catch (error) {
      console.error('Error loading tools:', error);
    }
  };

  const handleTestConnector = async (connector: Connector) => {
    try {
      const response = await fetch(`/api/aria/connectors/${connector.id}/test`, {
        method: 'POST',
      });

      const data = await response.json();

      if (data.success) {
        setConnectors((prev) =>
          prev.map((c) =>
            c.id === connector.id ? { ...c, status: 'connected' } : c
          )
        );
      } else {
        setConnectors((prev) =>
          prev.map((c) =>
            c.id === connector.id ? { ...c, status: 'error' } : c
          )
        );
      }
    } catch (error) {
      console.error('Error testing connector:', error);
    }
  };

  return (
    <div className="connector-manager">
      <div className="connector-header">
        <h2>🔌 Gestión de Conectores</h2>
        <button
          className="btn-primary"
          onClick={() => setShowAddForm(!showAddForm)}
        >
          {showAddForm ? 'Cancelar' : '+ Nuevo Conector'}
        </button>
      </div>

      {showAddForm && (
        <form className="connector-form" onSubmit={handleAddConnector}>
          <div className="form-group">
            <label>Nombre del Conector</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) =>
                setFormData({ ...formData, name: e.target.value })
              }
              placeholder="Mi Conector MCP"
              required
            />
          </div>

          <div className="form-group">
            <label>Tipo</label>
            <select
              value={formData.type}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  type: e.target.value as 'mcp' | 'zapier' | 'api',
                })
              }
            >
              <option value="mcp">MCP Server</option>
              <option value="zapier">Zapier</option>
              <option value="api">API Custom</option>
            </select>
          </div>

          {(formData.type === 'mcp' || formData.type === 'api') && (
            <div className="form-group">
              <label>URL del Servidor</label>
              <input
                type="url"
                value={formData.url}
                onChange={(e) =>
                  setFormData({ ...formData, url: e.target.value })
                }
                placeholder="https://mcp.example.com"
                required
              />
            </div>
          )}

          {formData.type === 'zapier' && (
            <div className="form-group">
              <label>API Key de Zapier</label>
              <input
                type="password"
                value={formData.apiKey}
                onChange={(e) =>
                  setFormData({ ...formData, apiKey: e.target.value })
                }
                placeholder="Tu API Key de Zapier"
                required
              />
            </div>
          )}

          <button type="submit" className="btn-primary">
            Conectar
          </button>
        </form>
      )}

      <div className="connectors-list">
        {connectors.map((connector) => (
          <div
            key={connector.id}
            className={`connector-card ${connector.status}`}
            onClick={() => handleSelectConnector(connector)}
          >
            <div className="connector-header-card">
              <h3>{connector.name}</h3>
              <span className={`status-badge ${connector.status}`}>
                {connector.status === 'connected' ? '🟢' : '🔴'} {connector.status}
              </span>
            </div>

            <p className="connector-type">Tipo: {connector.type.toUpperCase()}</p>

            {connector.tools && connector.tools.length > 0 && (
              <div className="connector-tools">
                <p className="tools-count">
                  {connector.tools.length} herramientas disponibles
                </p>
              </div>
            )}

            <div className="connector-actions">
              <button
                className="btn-secondary"
                onClick={(e) => {
                  e.stopPropagation();
                  handleTestConnector(connector);
                }}
              >
                Probar Conexión
              </button>
            </div>
          </div>
        ))}
      </div>

      {selectedConnector && (
        <div className="tools-panel">
          <h3>Herramientas de {selectedConnector.name}</h3>

          <div className="tools-list">
            {tools.map((tool) => (
              <div key={tool.name} className="tool-item">
                <h4>{tool.name}</h4>
                <p>{tool.description}</p>

                {tool.inputSchema && (
                  <details>
                    <summary>Parámetros</summary>
                    <pre>{JSON.stringify(tool.inputSchema, null, 2)}</pre>
                  </details>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <style jsx>{`
        .connector-manager {
          padding: 2rem;
        }

        .connector-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 2rem;
        }

        .connector-form {
          background: #161b22;
          padding: 1.5rem;
          border-radius: 8px;
          margin-bottom: 2rem;
          border: 1px solid #30363d;
        }

        .form-group {
          margin-bottom: 1rem;
        }

        .form-group label {
          display: block;
          margin-bottom: 0.5rem;
          font-weight: 600;
          color: #c9d1d9;
        }

        .form-group input,
        .form-group select {
          width: 100%;
          padding: 0.75rem;
          background: #0d1117;
          border: 1px solid #30363d;
          color: #c9d1d9;
          border-radius: 4px;
          font-family: inherit;
        }

        .connectors-list {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
          gap: 1rem;
          margin-bottom: 2rem;
        }

        .connector-card {
          background: #161b22;
          border: 2px solid #30363d;
          border-radius: 8px;
          padding: 1.5rem;
          cursor: pointer;
          transition: all 0.3s;
        }

        .connector-card:hover {
          border-color: #667eea;
          box-shadow: 0 0 12px rgba(102, 126, 234, 0.2);
        }

        .connector-card.connected {
          border-color: #238636;
        }

        .connector-card.error {
          border-color: #da3633;
        }

        .connector-header-card {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 1rem;
        }

        .connector-header-card h3 {
          margin: 0;
          color: #c9d1d9;
        }

        .status-badge {
          font-size: 0.85rem;
          padding: 0.25rem 0.75rem;
          border-radius: 12px;
          background: #30363d;
          color: #c9d1d9;
        }

        .status-badge.connected {
          background: #238636;
          color: white;
        }

        .status-badge.error {
          background: #da3633;
          color: white;
        }

        .connector-type {
          color: #8b949e;
          font-size: 0.9rem;
          margin: 0.5rem 0;
        }

        .connector-tools {
          margin: 1rem 0;
        }

        .tools-count {
          color: #667eea;
          font-size: 0.9rem;
          margin: 0;
        }

        .connector-actions {
          display: flex;
          gap: 0.5rem;
          margin-top: 1rem;
        }

        .btn-primary,
        .btn-secondary {
          padding: 0.5rem 1rem;
          border: none;
          border-radius: 4px;
          cursor: pointer;
          font-weight: 600;
          transition: all 0.2s;
        }

        .btn-primary {
          background: #667eea;
          color: white;
        }

        .btn-primary:hover {
          background: #5568d3;
        }

        .btn-secondary {
          background: #30363d;
          color: #c9d1d9;
          flex: 1;
        }

        .btn-secondary:hover {
          background: #3d444d;
        }

        .tools-panel {
          background: #161b22;
          border: 1px solid #30363d;
          border-radius: 8px;
          padding: 1.5rem;
          margin-top: 2rem;
        }

        .tools-list {
          display: grid;
          gap: 1rem;
          margin-top: 1rem;
        }

        .tool-item {
          background: #0d1117;
          padding: 1rem;
          border-radius: 4px;
          border-left: 3px solid #667eea;
        }

        .tool-item h4 {
          margin: 0 0 0.5rem 0;
          color: #c9d1d9;
        }

        .tool-item p {
          margin: 0;
          color: #8b949e;
          font-size: 0.9rem;
        }

        .tool-item details {
          margin-top: 0.5rem;
        }

        .tool-item summary {
          cursor: pointer;
          color: #667eea;
          font-size: 0.85rem;
        }

        .tool-item pre {
          background: #0d1117;
          padding: 0.5rem;
          border-radius: 4px;
          overflow-x: auto;
          font-size: 0.8rem;
        }
      `}</style>
    </div>
  );
};

export default ConnectorManager;

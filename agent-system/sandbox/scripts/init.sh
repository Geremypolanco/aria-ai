#!/bin/bash
# ARIA Sandbox — Script de inicialización
# Espera comandos desde STDIN y los ejecuta en entorno restringido
set -euo pipefail

echo "[SANDBOX] Iniciado. PID: $$"
echo "[SANDBOX] Listo para recibir comandos..."

while true; do
    if read -r cmd; then
        if [ "$cmd" = "exit" ] || [ "$cmd" = "quit" ]; then
            echo "[SANDBOX] Finalizando..."
            exit 0
        fi
        echo "[SANDBOX] Ejecutando: $cmd"
        eval "$cmd" 2>&1 || echo "[SANDBOX] Error: $?"
        echo "[SANDBOX] Comando completado. Listo para siguiente comando."
    fi
done

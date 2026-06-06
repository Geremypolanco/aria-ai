"""
demo_zapier_aria.py — Script de demostración para conectar Zapier con Aria.

Este script simula lo que Zapier enviaría a Aria a través de su webhook público.
Muestra cómo una tarea externa puede ser procesada por el orquestador de Aria.
"""

import json
import requests
import sys

def simulate_zapier_trigger(public_url: str, task: str):
    """Simula un trigger de Zapier enviando un webhook a Aria."""
    
    webhook_url = f"{public_url}/api/webhooks/zapier"
    
    payload = {
        "action": "new_email_received",
        "task": task,
        "data": {
            "from": "user@example.com",
            "subject": "Solicitud de Reporte",
            "body": "Por favor, investiga las últimas tendencias en IA autónoma y crea un resumen."
        },
        "user_id": "demo_user"
    }
    
    print(f"🚀 Enviando trigger de Zapier a: {webhook_url}")
    print(f"📝 Tarea: {task}")
    
    try:
        response = requests.post(webhook_url, json=payload, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        print("\n✅ Respuesta de Aria:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
    except requests.exceptions.RequestException as e:
        print(f"\n❌ Error conectando con Aria: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Detalles: {e.response.text}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python demo_zapier_aria.py <PUBLIC_URL>")
        sys.exit(1)
        
    public_url = sys.argv[1].rstrip('/')
    task = "Analiza el correo de user@example.com y genera un plan de investigación basado en su solicitud."
    
    simulate_zapier_trigger(public_url, task)

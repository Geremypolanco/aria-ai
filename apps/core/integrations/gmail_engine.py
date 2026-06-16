import os
import base64
import logging
from typing import List, Optional

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    _GOOGLE_AVAILABLE = True
except ImportError:
    _GOOGLE_AVAILABLE = False
    Credentials = None
    build = None
    HttpError = Exception

logger = logging.getLogger("aria.gmail_engine")

class GmailEngine:
    """Motor de ejecución real para Gmail API."""
    
    def __init__(self, credentials_path: str = "token.json"):
        self.creds = None
        self.service = None
        if not _GOOGLE_AVAILABLE:
            logger.warning("google-auth / google-api-python-client not installed — GmailEngine disabled")
            return
        if os.path.exists(credentials_path):
            self.creds = Credentials.from_authorized_user_file(credentials_path)
        self.service = build('gmail', 'v1', credentials=self.creds) if self.creds else None

    def search_and_cleanup(self, queries: List[str]) -> int:
        """Busca y elimina correos basados en una lista de queries."""
        if not self.service:
            logger.error("GmailEngine no autenticado. Por favor, configura tus credenciales.")
            return 0
            
        total_deleted = 0
        for query in queries:
            try:
                results = self.service.users().messages().list(userId='me', q=query).execute()
                messages = results.get('messages', [])
                
                if not messages:
                    continue
                    
                for msg in messages:
                    self.service.users().messages().delete(userId='me', id=msg['id']).execute()
                    total_deleted += 1
                logger.info(f"Query '{query}': {len(messages)} correos eliminados.")
            except HttpError as error:
                logger.error(f"Error en query '{query}': {error}")
                
        return total_deleted

    def send_notification(self, to: str, subject: str, body: str):
        """Envía un correo de notificación real."""
        if not self.service:
            return
            
        message = {
            'raw': base64.urlsafe_b64encode(
                f"To: {to}\r\nSubject: {subject}\r\n\r\n{body}".encode()
            ).decode()
        }
        try:
            self.service.users().messages().send(userId='me', body=message).execute()
            logger.info(f"Notificación enviada a {to}")
        except HttpError as error:
            logger.error(f"Error enviando correo: {error}")

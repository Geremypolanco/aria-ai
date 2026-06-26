import logging

import requests

logger = logging.getLogger("aria.linkedin_engine")


class LinkedInEngine:
    """Motor de ejecución real para LinkedIn API."""

    def __init__(self, access_token: str, person_id: str):
        self.access_token = access_token
        self.person_id = person_id
        self.base_url = "https://api.linkedin.com/v2"
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        }

    def create_viral_post(self, text: str, image_url: str | None = None):
        """Publica un post en el feed del usuario."""
        url = f"{self.base_url}/ugcPosts"
        payload = {
            "author": f"urn:li:person:{self.person_id}",
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
        }

        # Lógica simplificada: para imágenes se requiere un proceso de upload previo
        response = requests.post(url, json=payload, headers=self.headers)
        if response.status_code == 201:
            logger.info("Post viral publicado en LinkedIn.")
            return True
        logger.error(f"Error publicando en LinkedIn: {response.text}")
        return False

    def send_direct_message(self, recipient_urn: str, message: str):
        """Envía un mensaje directo de outreach."""
        url = f"{self.base_url}/messages"
        payload = {
            "recipients": [recipient_urn],
            "subject": "Oportunidad de Negocio - Aria AI",
            "body": message,
        }
        response = requests.post(url, json=payload, headers=self.headers)
        if response.status_code == 201:
            logger.info(f"Mensaje enviado a {recipient_urn}")
            return True
        return False

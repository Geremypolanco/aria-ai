import logging

import requests

logger = logging.getLogger("aria.linkedin_engine")


class LinkedInEngine:
    """Real execution engine for LinkedIn API."""

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
        """Publishes a post to the user's feed."""
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

        # Simplified logic: images require a prior upload process
        response = requests.post(url, json=payload, headers=self.headers)
        if response.status_code == 201:
            logger.info("Viral post published on LinkedIn.")
            return True
        logger.error(f"Error publishing on LinkedIn: {response.text}")
        return False

    def send_direct_message(self, recipient_urn: str, message: str):
        """Sends a direct outreach message."""
        url = f"{self.base_url}/messages"
        payload = {
            "recipients": [recipient_urn],
            "subject": "Business Opportunity - Aria AI",
            "body": message,
        }
        response = requests.post(url, json=payload, headers=self.headers)
        if response.status_code == 201:
            logger.info(f"Message sent to {recipient_urn}")
            return True
        return False

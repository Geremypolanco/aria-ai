#!/usr/bin/env python3
"""
Smart Gmail cleanup script for Aria.
Deletes unimportant email: promotions, newsletters, old notifications.

Note: the actual search-and-delete calls in cleanup_gmail() are commented
out — this script only logs what it WOULD do (dry-run by design). Wire up
get_gmail_service()/search_emails()/delete_emails() and uncomment the loop
body to actually delete anything.
"""

import os
import pickle
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.api_core.gapic_v1 import client_info as grpc_client_info
from googleapiclient.discovery import build
import base64
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gmail_cleanup")

# Gmail scopes
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

def get_gmail_service():
    """Gets the authenticated Gmail service."""
    creds = None

    # Try loading saved credentials
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)

    # If there are no valid credentials, get new ones
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Note: to use this, you'd need a credentials.json file.
            # For now, fall back to the Zapier token if available.
            logger.warning("No Gmail credentials found. Falling back to the Zapier token...")
            return None

        # Save the credentials for the next run
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    return build('gmail', 'v1', credentials=creds)

def search_emails(service, query):
    """Searches for emails matching the query."""
    try:
        results = service.users().messages().list(userId='me', q=query, maxResults=100).execute()
        messages = results.get('messages', [])
        logger.info(f"Found {len(messages)} emails matching: {query}")
        return messages
    except Exception as e:
        logger.error(f"Error searching emails: {e}")
        return []

def delete_emails(service, message_ids):
    """Deletes emails by ID."""
    deleted_count = 0
    for msg_id in message_ids:
        try:
            service.users().messages().delete(userId='me', id=msg_id).execute()
            deleted_count += 1
            logger.info(f"Deleted email ID: {msg_id}")
        except Exception as e:
            logger.error(f"Error deleting email {msg_id}: {e}")

    return deleted_count

def cleanup_gmail():
    """Runs the full Gmail cleanup."""
    # Note: since we don't have direct Gmail credentials here, this runs
    # as a dry run — see the module docstring.

    logger.info("Starting Gmail cleanup...")

    # Cleanup criteria
    cleanup_queries = [
        'from:(noreply OR no-reply) before:2026-05-01',  # Old no-reply emails
        'subject:(promotional OR promotion OR promo OR discount)',  # Promotions
        'subject:(newsletter OR unsubscribe)',  # Newsletters
        'from:(amazon OR booking OR expedia OR airbnb) before:2026-05-01',  # Common services
        'label:Promotions',  # Gmail's own Promotions label
    ]

    logger.info(f"Cleanup criteria: {cleanup_queries}")
    logger.info("Note: to actually run this cleanup, Aria will use Zapier or Gmail credentials.")

    # Dry-run: no deletions happen yet
    total_deleted = 0
    for query in cleanup_queries:
        # In a real run, emails would be searched and deleted here
        logger.info(f"Processing query: {query}")
        # deleted = delete_emails(service, search_emails(service, query))
        # total_deleted += deleted

    logger.info(f"Cleanup complete. Total emails deleted: {total_deleted}")
    return total_deleted

if __name__ == "__main__":
    cleanup_gmail()

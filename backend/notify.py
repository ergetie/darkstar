"""
Notification Utilities

Provides fallback notification support when Home Assistant is unavailable.
Tries HA notification first, falls back to Discord webhook.
"""

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)


def send_critical_notification(
    title: str,
    message: str,
    ha_service: Optional[str] = None,
    ha_url: Optional[str] = None,
    ha_token: Optional[str] = None,
    discord_webhook_url: Optional[str] = None,
) -> bool:
    """
    Send a critical notification with fallback support.
    
    Tries Home Assistant first, falls back to Discord webhook.
    
    Args:
        title: Notification title
        message: Notification message
        ha_service: HA notification service (e.g., "notify.mobile_app_phone")
        ha_url: Home Assistant URL
        ha_token: Home Assistant long-lived access token
        discord_webhook_url: Discord webhook URL for fallback
        
    Returns:
        True if notification was sent successfully via any method
    """
    # Try Home Assistant first
    if ha_service and ha_url and ha_token:
        if _send_ha_notification(ha_service, title, message, ha_url, ha_token):
            logger.info("Critical notification sent via Home Assistant")
            return True
        logger.warning("Home Assistant notification failed, trying fallback...")
    
    # Fallback to Discord
    if discord_webhook_url:
        if _send_discord_notification(discord_webhook_url, title, message):
            logger.info("Critical notification sent via Discord webhook")
            return True
        logger.error("Discord notification also failed")
    
    logger.error("All notification methods failed for: %s", title)
    return False


def _send_ha_notification(
    service: str,
    title: str,
    message: str,
    ha_url: str,
    ha_token: str,
    timeout: int = 10,
) -> bool:
    """Send notification via Home Assistant."""
    try:
        # Parse service (e.g., "notify.mobile_app_phone" -> domain="notify", service="mobile_app_phone")
        parts = service.split(".", 1)
        if len(parts) != 2:
            logger.error("Invalid HA notification service format: %s", service)
            return False
        
        domain, svc_name = parts
        endpoint = f"{ha_url.rstrip('/')}/api/services/{domain}/{svc_name}"
        
        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {ha_token}",
                "Content-Type": "application/json",
            },
            json={"title": title, "message": message},
            timeout=timeout,
        )
        response.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.warning("HA notification failed: %s", e)
        return False


def _send_discord_notification(
    webhook_url: str,
    title: str,
    message: str,
    timeout: int = 10,
) -> bool:
    """Send notification via Discord webhook."""
    try:
        # Discord embed format for nicer display
        payload = {
            "embeds": [
                {
                    "title": f"⚠️ {title}",
                    "description": message,
                    "color": 0xFF0000,  # Red for critical
                }
            ]
        }
        
        response = requests.post(
            webhook_url,
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.warning("Discord notification failed: %s", e)
        return False

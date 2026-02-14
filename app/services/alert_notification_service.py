"""Alert notification service for sending Slack webhook and email notifications."""

import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Dict, Any, List, Optional
from loguru import logger
import httpx


class AlertNotificationService:
    """Service for sending alert notifications via Slack webhooks and email."""

    # ============================================
    # SLACK WEBHOOK NOTIFICATIONS
    # ============================================

    def send_slack_notification(
        self,
        webhook_url: str,
        alert_name: str,
        alert_description: Optional[str],
        metric_type: str,
        aggregation: str,
        operator: str,
        threshold_value: float,
        triggered_value: float,
        time_window_minutes: int,
        triggered_at: datetime,
        agent_names: Optional[List[str]] = None,
        alert_id: Optional[str] = None,
        history_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a Slack notification via incoming webhook.

        Args:
            webhook_url: Slack incoming webhook URL
            alert_name: Name of the alert
            alert_description: Description of the alert
            metric_type: Type of metric (e.g., "number_of_calls")
            aggregation: Aggregation type (e.g., "sum")
            operator: Comparison operator (e.g., ">")
            threshold_value: The configured threshold
            triggered_value: The actual value that triggered the alert
            time_window_minutes: Time window for the metric
            triggered_at: When the alert was triggered
            agent_names: Optional list of agent names in scope
            alert_id: Optional alert ID for reference
            history_id: Optional alert history ID for reference

        Returns:
            Dict with success status and details
        """
        try:
            # Build Slack Block Kit message
            severity_emoji = self._get_severity_emoji(
                operator, threshold_value, triggered_value
            )
            metric_display = metric_type.replace("_", " ").title()
            agent_scope = (
                ", ".join(agent_names) if agent_names else "All Agents"
            )

            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{severity_emoji} Alert Triggered: {alert_name}",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Metric:*\n{metric_display}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Aggregation:*\n{aggregation.upper()}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Condition:*\n{operator} {threshold_value}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Actual Value:*\n*{triggered_value}*",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Time Window:*\n{time_window_minutes} minutes",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Agent Scope:*\n{agent_scope}",
                        },
                    ],
                },
                {"type": "divider"},
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": (
                                f"Triggered at {triggered_at.strftime('%Y-%m-%d %H:%M:%S UTC')}"
                                f" | EfficientAI Alerting"
                            ),
                        }
                    ],
                },
            ]

            # Add description if provided
            if alert_description:
                blocks.insert(
                    2,
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"_{alert_description}_",
                        },
                    },
                )

            payload = {
                "text": (
                    f"{severity_emoji} Alert '{alert_name}': {metric_display} "
                    f"({aggregation}) is {triggered_value} (threshold: {operator} {threshold_value})"
                ),
                "blocks": blocks,
            }

            # Send to Slack webhook
            with httpx.Client(timeout=30.0) as client:
                response = client.post(webhook_url, json=payload)

            if response.status_code == 200:
                logger.info(
                    f"[AlertNotification] Slack notification sent successfully "
                    f"for alert '{alert_name}' to webhook"
                )
                return {
                    "success": True,
                    "channel": "slack_webhook",
                    "webhook_url": self._mask_webhook_url(webhook_url),
                }
            else:
                logger.error(
                    f"[AlertNotification] Slack webhook returned {response.status_code}: "
                    f"{response.text}"
                )
                return {
                    "success": False,
                    "channel": "slack_webhook",
                    "error": f"HTTP {response.status_code}: {response.text}",
                    "webhook_url": self._mask_webhook_url(webhook_url),
                }

        except Exception as e:
            logger.error(
                f"[AlertNotification] Failed to send Slack notification: {e}",
                exc_info=True,
            )
            return {
                "success": False,
                "channel": "slack_webhook",
                "error": str(e),
                "webhook_url": self._mask_webhook_url(webhook_url),
            }

    # ============================================
    # EMAIL NOTIFICATIONS
    # ============================================

    def send_email_notification(
        self,
        to_email: str,
        alert_name: str,
        alert_description: Optional[str],
        metric_type: str,
        aggregation: str,
        operator: str,
        threshold_value: float,
        triggered_value: float,
        time_window_minutes: int,
        triggered_at: datetime,
        agent_names: Optional[List[str]] = None,
        alert_id: Optional[str] = None,
        history_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send an email notification for a triggered alert.

        Args:
            to_email: Recipient email address
            alert_name: Name of the alert
            alert_description: Description of the alert
            metric_type: Type of metric
            aggregation: Aggregation type
            operator: Comparison operator
            threshold_value: The configured threshold
            triggered_value: The actual value that triggered the alert
            time_window_minutes: Time window for the metric
            triggered_at: When the alert was triggered
            agent_names: Optional list of agent names in scope
            alert_id: Optional alert ID for reference
            history_id: Optional alert history ID for reference

        Returns:
            Dict with success status and details
        """
        from app.config import settings

        # Check SMTP configuration
        if not settings.SMTP_HOST:
            logger.warning(
                "[AlertNotification] SMTP not configured, skipping email notification"
            )
            return {
                "success": False,
                "channel": "email",
                "error": "SMTP not configured. Set SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD in config.",
                "to_email": to_email,
            }

        try:
            metric_display = metric_type.replace("_", " ").title()
            agent_scope = (
                ", ".join(agent_names) if agent_names else "All Agents"
            )
            severity_label = self._get_severity_label(
                operator, threshold_value, triggered_value
            )

            # Build email
            msg = MIMEMultipart("alternative")
            msg["Subject"] = (
                f"[{severity_label}] EfficientAI Alert: {alert_name}"
            )
            msg["From"] = (
                f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL or settings.SMTP_USERNAME}>"
            )
            msg["To"] = to_email

            # Plain text version
            text_body = self._build_email_text(
                alert_name=alert_name,
                alert_description=alert_description,
                metric_display=metric_display,
                aggregation=aggregation,
                operator=operator,
                threshold_value=threshold_value,
                triggered_value=triggered_value,
                time_window_minutes=time_window_minutes,
                triggered_at=triggered_at,
                agent_scope=agent_scope,
                severity_label=severity_label,
            )

            # HTML version
            html_body = self._build_email_html(
                alert_name=alert_name,
                alert_description=alert_description,
                metric_display=metric_display,
                aggregation=aggregation,
                operator=operator,
                threshold_value=threshold_value,
                triggered_value=triggered_value,
                time_window_minutes=time_window_minutes,
                triggered_at=triggered_at,
                agent_scope=agent_scope,
                severity_label=severity_label,
            )

            msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))

            # Send email
            if settings.SMTP_USE_TLS:
                context = ssl.create_default_context()
                with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                    server.ehlo()
                    server.starttls(context=context)
                    server.ehlo()
                    if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                    server.sendmail(
                        settings.SMTP_FROM_EMAIL or settings.SMTP_USERNAME,
                        to_email,
                        msg.as_string(),
                    )
            else:
                with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                    if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
                        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                    server.sendmail(
                        settings.SMTP_FROM_EMAIL or settings.SMTP_USERNAME,
                        to_email,
                        msg.as_string(),
                    )

            logger.info(
                f"[AlertNotification] Email sent successfully "
                f"for alert '{alert_name}' to {to_email}"
            )
            return {
                "success": True,
                "channel": "email",
                "to_email": to_email,
            }

        except Exception as e:
            logger.error(
                f"[AlertNotification] Failed to send email to {to_email}: {e}",
                exc_info=True,
            )
            return {
                "success": False,
                "channel": "email",
                "error": str(e),
                "to_email": to_email,
            }

    # ============================================
    # BATCH NOTIFICATION DISPATCHER
    # ============================================

    def send_all_notifications(
        self,
        alert,
        triggered_value: float,
        triggered_at: datetime,
        agent_names: Optional[List[str]] = None,
        history_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Send notifications to all configured channels for an alert.

        Args:
            alert: Alert ORM object with notification configuration
            triggered_value: The actual value that triggered the alert
            triggered_at: When the alert was triggered
            agent_names: Optional list of agent names in scope
            history_id: Optional alert history ID for reference

        Returns:
            List of notification results
        """
        results = []

        common_params = dict(
            alert_name=alert.name,
            alert_description=alert.description,
            metric_type=alert.metric_type,
            aggregation=alert.aggregation,
            operator=alert.operator,
            threshold_value=alert.threshold_value,
            triggered_value=triggered_value,
            time_window_minutes=alert.time_window_minutes,
            triggered_at=triggered_at,
            agent_names=agent_names,
            alert_id=str(alert.id),
            history_id=history_id,
        )

        # Send to all configured Slack webhooks
        if alert.notify_webhooks:
            for webhook_url in alert.notify_webhooks:
                if webhook_url and webhook_url.strip():
                    result = self.send_slack_notification(
                        webhook_url=webhook_url.strip(),
                        **common_params,
                    )
                    results.append(result)

        # Send to all configured email addresses
        if alert.notify_emails:
            for email_addr in alert.notify_emails:
                if email_addr and email_addr.strip():
                    result = self.send_email_notification(
                        to_email=email_addr.strip(),
                        **common_params,
                    )
                    results.append(result)

        logger.info(
            f"[AlertNotification] Dispatched {len(results)} notifications for alert '{alert.name}': "
            f"{sum(1 for r in results if r.get('success'))} succeeded, "
            f"{sum(1 for r in results if not r.get('success'))} failed"
        )

        return results

    # ============================================
    # HELPER METHODS
    # ============================================

    def _get_severity_emoji(
        self, operator: str, threshold: float, actual: float
    ) -> str:
        """Get severity emoji based on how much the threshold is exceeded."""
        if operator in (">", ">="):
            ratio = actual / threshold if threshold > 0 else 2.0
            if ratio >= 2.0:
                return "\U0001f6a8"  # rotating light
            elif ratio >= 1.5:
                return "\u26a0\ufe0f"  # warning
            else:
                return "\U0001f514"  # bell
        elif operator in ("<", "<="):
            ratio = threshold / actual if actual > 0 else 2.0
            if ratio >= 2.0:
                return "\U0001f6a8"
            elif ratio >= 1.5:
                return "\u26a0\ufe0f"
            else:
                return "\U0001f514"
        return "\U0001f514"

    def _get_severity_label(
        self, operator: str, threshold: float, actual: float
    ) -> str:
        """Get severity label for email subject."""
        if operator in (">", ">="):
            ratio = actual / threshold if threshold > 0 else 2.0
        elif operator in ("<", "<="):
            ratio = threshold / actual if actual > 0 else 2.0
        else:
            ratio = 1.0

        if ratio >= 2.0:
            return "CRITICAL"
        elif ratio >= 1.5:
            return "WARNING"
        return "ALERT"

    def _mask_webhook_url(self, url: str) -> str:
        """Mask webhook URL for logging (show only first and last parts)."""
        if len(url) > 40:
            return url[:25] + "..." + url[-10:]
        return url[:10] + "..."

    def _build_email_text(
        self,
        alert_name: str,
        alert_description: Optional[str],
        metric_display: str,
        aggregation: str,
        operator: str,
        threshold_value: float,
        triggered_value: float,
        time_window_minutes: int,
        triggered_at: datetime,
        agent_scope: str,
        severity_label: str,
    ) -> str:
        """Build plain text email body."""
        desc_line = f"\n{alert_description}\n" if alert_description else ""
        return f"""EfficientAI Alert Notification
{'=' * 40}

Alert: {alert_name}
Severity: {severity_label}
{desc_line}
Metric Details:
  - Metric: {metric_display}
  - Aggregation: {aggregation.upper()}
  - Condition: {operator} {threshold_value}
  - Actual Value: {triggered_value}
  - Time Window: {time_window_minutes} minutes
  - Agent Scope: {agent_scope}

Triggered At: {triggered_at.strftime('%Y-%m-%d %H:%M:%S UTC')}

---
This is an automated alert from EfficientAI.
Please review the alert in the EfficientAI dashboard.
"""

    def _build_email_html(
        self,
        alert_name: str,
        alert_description: Optional[str],
        metric_display: str,
        aggregation: str,
        operator: str,
        threshold_value: float,
        triggered_value: float,
        time_window_minutes: int,
        triggered_at: datetime,
        agent_scope: str,
        severity_label: str,
    ) -> str:
        """Build HTML email body."""
        severity_color = {
            "CRITICAL": "#DC2626",
            "WARNING": "#F59E0B",
            "ALERT": "#3B82F6",
        }.get(severity_label, "#3B82F6")

        desc_html = (
            f'<p style="color: #6B7280; font-style: italic; margin: 0 0 16px 0;">'
            f"{alert_description}</p>"
            if alert_description
            else ""
        )

        return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #F3F4F6; padding: 20px; margin: 0;">
  <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
    <!-- Header -->
    <div style="background-color: {severity_color}; padding: 20px 24px;">
      <h1 style="color: white; margin: 0; font-size: 18px; font-weight: 600;">
        {severity_label}: {alert_name}
      </h1>
    </div>

    <!-- Body -->
    <div style="padding: 24px;">
      {desc_html}

      <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
        <tr>
          <td style="padding: 10px 12px; border-bottom: 1px solid #E5E7EB; color: #6B7280; font-size: 13px; width: 40%;">Metric</td>
          <td style="padding: 10px 12px; border-bottom: 1px solid #E5E7EB; font-weight: 600; font-size: 14px;">{metric_display}</td>
        </tr>
        <tr>
          <td style="padding: 10px 12px; border-bottom: 1px solid #E5E7EB; color: #6B7280; font-size: 13px;">Aggregation</td>
          <td style="padding: 10px 12px; border-bottom: 1px solid #E5E7EB; font-weight: 600; font-size: 14px;">{aggregation.upper()}</td>
        </tr>
        <tr>
          <td style="padding: 10px 12px; border-bottom: 1px solid #E5E7EB; color: #6B7280; font-size: 13px;">Condition</td>
          <td style="padding: 10px 12px; border-bottom: 1px solid #E5E7EB; font-weight: 600; font-size: 14px;">{operator} {threshold_value}</td>
        </tr>
        <tr style="background-color: #FEF2F2;">
          <td style="padding: 10px 12px; border-bottom: 1px solid #E5E7EB; color: #6B7280; font-size: 13px;">Actual Value</td>
          <td style="padding: 10px 12px; border-bottom: 1px solid #E5E7EB; font-weight: 700; font-size: 16px; color: {severity_color};">{triggered_value}</td>
        </tr>
        <tr>
          <td style="padding: 10px 12px; border-bottom: 1px solid #E5E7EB; color: #6B7280; font-size: 13px;">Time Window</td>
          <td style="padding: 10px 12px; border-bottom: 1px solid #E5E7EB; font-weight: 600; font-size: 14px;">{time_window_minutes} minutes</td>
        </tr>
        <tr>
          <td style="padding: 10px 12px; border-bottom: 1px solid #E5E7EB; color: #6B7280; font-size: 13px;">Agent Scope</td>
          <td style="padding: 10px 12px; border-bottom: 1px solid #E5E7EB; font-weight: 600; font-size: 14px;">{agent_scope}</td>
        </tr>
      </table>

      <p style="color: #6B7280; font-size: 12px; margin: 0;">
        Triggered at {triggered_at.strftime('%Y-%m-%d %H:%M:%S UTC')}
      </p>
    </div>

    <!-- Footer -->
    <div style="background-color: #F9FAFB; padding: 16px 24px; border-top: 1px solid #E5E7EB;">
      <p style="color: #9CA3AF; font-size: 12px; margin: 0; text-align: center;">
        This is an automated alert from EfficientAI. Review alerts in your dashboard.
      </p>
    </div>
  </div>
</body>
</html>"""


# Singleton instance
alert_notification_service = AlertNotificationService()

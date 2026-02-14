"""Alert evaluation service for checking alert conditions and triggering notifications."""

import operator as op_module
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from app.models.database import (
    Alert,
    AlertHistory,
    Agent,
    EvaluatorResult,
)
from app.models.enums import (
    AlertStatus,
    AlertHistoryStatus,
    AlertMetricType,
    AlertAggregation,
    AlertOperator,
    AlertNotifyFrequency,
    EvaluatorResultStatus,
)
from app.services.alert_notification_service import alert_notification_service


# Operator mapping
OPERATOR_MAP = {
    AlertOperator.GREATER_THAN.value: op_module.gt,
    AlertOperator.LESS_THAN.value: op_module.lt,
    AlertOperator.GREATER_THAN_OR_EQUAL.value: op_module.ge,
    AlertOperator.LESS_THAN_OR_EQUAL.value: op_module.le,
    AlertOperator.EQUAL.value: op_module.eq,
    AlertOperator.NOT_EQUAL.value: op_module.ne,
    # Also handle enum values directly
    ">": op_module.gt,
    "<": op_module.lt,
    ">=": op_module.ge,
    "<=": op_module.le,
    "=": op_module.eq,
    "!=": op_module.ne,
}

# Notification frequency cooldown mapping (in seconds)
FREQUENCY_COOLDOWN = {
    AlertNotifyFrequency.IMMEDIATE.value: 0,
    AlertNotifyFrequency.HOURLY.value: 3600,
    AlertNotifyFrequency.DAILY.value: 86400,
    AlertNotifyFrequency.WEEKLY.value: 604800,
    "immediate": 0,
    "hourly": 3600,
    "daily": 86400,
    "weekly": 604800,
}


class AlertEvaluationService:
    """Service for evaluating alert conditions against real-time metrics."""

    def evaluate_all_alerts(self, db: Session) -> Dict[str, Any]:
        """
        Evaluate all active alerts across all organizations.

        Args:
            db: Database session

        Returns:
            Summary of evaluation results
        """
        logger.info("[AlertEvaluation] Starting evaluation of all active alerts")

        # Get all active alerts
        active_alerts = (
            db.query(Alert)
            .filter(Alert.status == AlertStatus.ACTIVE.value)
            .all()
        )

        logger.info(f"[AlertEvaluation] Found {len(active_alerts)} active alerts to evaluate")

        results = {
            "total_alerts": len(active_alerts),
            "triggered": 0,
            "not_triggered": 0,
            "errors": 0,
            "skipped_cooldown": 0,
            "details": [],
        }

        for alert in active_alerts:
            try:
                result = self.evaluate_single_alert(alert, db)
                results["details"].append(result)

                if result.get("triggered"):
                    results["triggered"] += 1
                elif result.get("skipped_cooldown"):
                    results["skipped_cooldown"] += 1
                else:
                    results["not_triggered"] += 1

            except Exception as e:
                logger.error(
                    f"[AlertEvaluation] Error evaluating alert '{alert.name}' "
                    f"(id={alert.id}): {e}",
                    exc_info=True,
                )
                results["errors"] += 1
                results["details"].append(
                    {
                        "alert_id": str(alert.id),
                        "alert_name": alert.name,
                        "error": str(e),
                    }
                )

        logger.info(
            f"[AlertEvaluation] Evaluation complete: "
            f"{results['triggered']} triggered, "
            f"{results['not_triggered']} not triggered, "
            f"{results['skipped_cooldown']} skipped (cooldown), "
            f"{results['errors']} errors"
        )

        return results

    def evaluate_single_alert(
        self, alert: Alert, db: Session
    ) -> Dict[str, Any]:
        """
        Evaluate a single alert's condition.

        Args:
            alert: Alert ORM object
            db: Database session

        Returns:
            Evaluation result dict
        """
        alert_name = alert.name
        logger.debug(f"[AlertEvaluation] Evaluating alert '{alert_name}'")

        # Step 1: Check notification cooldown
        if not self._should_notify(alert, db):
            logger.debug(
                f"[AlertEvaluation] Alert '{alert_name}' skipped due to notification cooldown"
            )
            return {
                "alert_id": str(alert.id),
                "alert_name": alert_name,
                "triggered": False,
                "skipped_cooldown": True,
                "reason": "Notification cooldown active",
            }

        # Step 2: Compute the metric value
        metric_value = self._compute_metric(alert, db)

        if metric_value is None:
            logger.debug(
                f"[AlertEvaluation] Alert '{alert_name}': no data available for metric"
            )
            return {
                "alert_id": str(alert.id),
                "alert_name": alert_name,
                "triggered": False,
                "metric_value": None,
                "reason": "No data available for metric computation",
            }

        # Step 3: Compare against threshold
        operator_str = alert.operator
        threshold = alert.threshold_value
        compare_fn = OPERATOR_MAP.get(operator_str)

        if compare_fn is None:
            logger.error(
                f"[AlertEvaluation] Unknown operator '{operator_str}' "
                f"for alert '{alert_name}'"
            )
            return {
                "alert_id": str(alert.id),
                "alert_name": alert_name,
                "triggered": False,
                "error": f"Unknown operator: {operator_str}",
            }

        is_triggered = compare_fn(metric_value, threshold)

        logger.info(
            f"[AlertEvaluation] Alert '{alert_name}': "
            f"{metric_value} {operator_str} {threshold} = {is_triggered}"
        )

        if is_triggered:
            # Step 4: Create alert history record and send notifications
            return self._trigger_alert(
                alert=alert,
                triggered_value=metric_value,
                db=db,
            )

        return {
            "alert_id": str(alert.id),
            "alert_name": alert_name,
            "triggered": False,
            "metric_value": metric_value,
            "threshold": threshold,
            "operator": operator_str,
        }

    def evaluate_alert_by_id(
        self, alert_id: UUID, organization_id: UUID, db: Session
    ) -> Dict[str, Any]:
        """
        Evaluate a specific alert by ID (manual trigger).

        Args:
            alert_id: Alert UUID
            organization_id: Organization UUID
            db: Database session

        Returns:
            Evaluation result dict
        """
        alert = (
            db.query(Alert)
            .filter(
                and_(
                    Alert.id == alert_id,
                    Alert.organization_id == organization_id,
                )
            )
            .first()
        )

        if not alert:
            return {"error": "Alert not found"}

        return self.evaluate_single_alert(alert, db)

    # ============================================
    # METRIC COMPUTATION
    # ============================================

    def _compute_metric(
        self, alert: Alert, db: Session
    ) -> Optional[float]:
        """
        Compute the aggregated metric value for an alert.

        Args:
            alert: Alert ORM object
            db: Database session

        Returns:
            Computed metric value, or None if no data
        """
        metric_type = alert.metric_type
        aggregation = alert.aggregation
        time_window = alert.time_window_minutes
        organization_id = alert.organization_id
        agent_ids = alert.agent_ids  # JSON list of agent UUID strings, or None

        # Calculate the time boundary
        now = datetime.utcnow()
        window_start = now - timedelta(minutes=time_window)

        # Route to the appropriate metric calculator
        if metric_type in (
            AlertMetricType.NUMBER_OF_CALLS.value,
            "number_of_calls",
        ):
            return self._compute_number_of_calls(
                db, organization_id, agent_ids, window_start, aggregation
            )
        elif metric_type in (
            AlertMetricType.CALL_DURATION.value,
            "call_duration",
        ):
            return self._compute_call_duration(
                db, organization_id, agent_ids, window_start, aggregation
            )
        elif metric_type in (
            AlertMetricType.ERROR_RATE.value,
            "error_rate",
        ):
            return self._compute_error_rate(
                db, organization_id, agent_ids, window_start, aggregation
            )
        elif metric_type in (
            AlertMetricType.SUCCESS_RATE.value,
            "success_rate",
        ):
            return self._compute_success_rate(
                db, organization_id, agent_ids, window_start, aggregation
            )
        elif metric_type in (
            AlertMetricType.LATENCY.value,
            "latency",
        ):
            return self._compute_latency(
                db, organization_id, agent_ids, window_start, aggregation
            )
        elif metric_type in (
            AlertMetricType.CUSTOM.value,
            "custom",
        ):
            return self._compute_custom_metric(
                db, organization_id, agent_ids, window_start, aggregation
            )
        else:
            logger.warning(
                f"[AlertEvaluation] Unknown metric type: {metric_type}"
            )
            return None

    def _build_evaluator_result_query(
        self,
        db: Session,
        organization_id: UUID,
        agent_ids: Optional[list],
        window_start: datetime,
    ):
        """Build base query for EvaluatorResult filtered by org, agents, and time."""
        query = db.query(EvaluatorResult).filter(
            and_(
                EvaluatorResult.organization_id == organization_id,
                EvaluatorResult.created_at >= window_start,
            )
        )

        if agent_ids:
            # agent_ids is a JSON list of UUID strings
            agent_uuid_list = [UUID(aid) if isinstance(aid, str) else aid for aid in agent_ids]
            query = query.filter(EvaluatorResult.agent_id.in_(agent_uuid_list))

        return query

    def _compute_number_of_calls(
        self,
        db: Session,
        organization_id: UUID,
        agent_ids: Optional[list],
        window_start: datetime,
        aggregation: str,
    ) -> Optional[float]:
        """Compute number of calls (evaluator results) in the time window."""
        query = self._build_evaluator_result_query(
            db, organization_id, agent_ids, window_start
        )

        # For number_of_calls, count is the primary metric regardless of aggregation
        count = query.count()
        return float(count)

    def _compute_call_duration(
        self,
        db: Session,
        organization_id: UUID,
        agent_ids: Optional[list],
        window_start: datetime,
        aggregation: str,
    ) -> Optional[float]:
        """Compute call duration metric with the specified aggregation."""
        query = self._build_evaluator_result_query(
            db, organization_id, agent_ids, window_start
        ).filter(EvaluatorResult.duration_seconds.isnot(None))

        return self._apply_aggregation(
            db, query, EvaluatorResult.duration_seconds, aggregation
        )

    def _compute_error_rate(
        self,
        db: Session,
        organization_id: UUID,
        agent_ids: Optional[list],
        window_start: datetime,
        aggregation: str,
    ) -> Optional[float]:
        """Compute error rate as percentage of failed evaluator results."""
        query = self._build_evaluator_result_query(
            db, organization_id, agent_ids, window_start
        )

        total = query.count()
        if total == 0:
            return None

        failed = query.filter(
            EvaluatorResult.status == EvaluatorResultStatus.FAILED.value
        ).count()

        return round((failed / total) * 100, 2)

    def _compute_success_rate(
        self,
        db: Session,
        organization_id: UUID,
        agent_ids: Optional[list],
        window_start: datetime,
        aggregation: str,
    ) -> Optional[float]:
        """Compute success rate as percentage of completed evaluator results."""
        query = self._build_evaluator_result_query(
            db, organization_id, agent_ids, window_start
        )

        total = query.count()
        if total == 0:
            return None

        completed = query.filter(
            EvaluatorResult.status == EvaluatorResultStatus.COMPLETED.value
        ).count()

        return round((completed / total) * 100, 2)

    def _compute_latency(
        self,
        db: Session,
        organization_id: UUID,
        agent_ids: Optional[list],
        window_start: datetime,
        aggregation: str,
    ) -> Optional[float]:
        """
        Compute latency metric.
        Uses duration_seconds from EvaluatorResult as a proxy for latency.
        """
        query = self._build_evaluator_result_query(
            db, organization_id, agent_ids, window_start
        ).filter(EvaluatorResult.duration_seconds.isnot(None))

        return self._apply_aggregation(
            db, query, EvaluatorResult.duration_seconds, aggregation
        )

    def _compute_custom_metric(
        self,
        db: Session,
        organization_id: UUID,
        agent_ids: Optional[list],
        window_start: datetime,
        aggregation: str,
    ) -> Optional[float]:
        """
        Compute custom metric - counts all evaluator results.
        Custom metrics can be extended based on specific requirements.
        """
        query = self._build_evaluator_result_query(
            db, organization_id, agent_ids, window_start
        )
        count = query.count()
        return float(count) if count > 0 else None

    def _apply_aggregation(
        self,
        db: Session,
        query,
        column,
        aggregation: str,
    ) -> Optional[float]:
        """Apply SQL aggregation function to a query column."""
        agg_str = aggregation.lower() if isinstance(aggregation, str) else aggregation

        if agg_str in (AlertAggregation.SUM.value, "sum"):
            result = db.query(func.sum(column)).filter(
                EvaluatorResult.id.in_(query.with_entities(EvaluatorResult.id).subquery().select())
            ).scalar()
        elif agg_str in (AlertAggregation.AVG.value, "avg"):
            result = db.query(func.avg(column)).filter(
                EvaluatorResult.id.in_(query.with_entities(EvaluatorResult.id).subquery().select())
            ).scalar()
        elif agg_str in (AlertAggregation.COUNT.value, "count"):
            result = query.count()
        elif agg_str in (AlertAggregation.MIN.value, "min"):
            result = db.query(func.min(column)).filter(
                EvaluatorResult.id.in_(query.with_entities(EvaluatorResult.id).subquery().select())
            ).scalar()
        elif agg_str in (AlertAggregation.MAX.value, "max"):
            result = db.query(func.max(column)).filter(
                EvaluatorResult.id.in_(query.with_entities(EvaluatorResult.id).subquery().select())
            ).scalar()
        else:
            logger.warning(f"[AlertEvaluation] Unknown aggregation: {aggregation}")
            return None

        return float(result) if result is not None else None

    # ============================================
    # NOTIFICATION COOLDOWN
    # ============================================

    def _should_notify(self, alert: Alert, db: Session) -> bool:
        """
        Check if the alert should send a notification based on frequency cooldown.

        Args:
            alert: Alert ORM object
            db: Database session

        Returns:
            True if notification should be sent
        """
        frequency = alert.notify_frequency
        cooldown_seconds = FREQUENCY_COOLDOWN.get(frequency, 0)

        if cooldown_seconds == 0:
            return True

        # Check the last notification time for this alert
        last_notified = (
            db.query(AlertHistory)
            .filter(
                and_(
                    AlertHistory.alert_id == alert.id,
                    AlertHistory.notified_at.isnot(None),
                )
            )
            .order_by(AlertHistory.notified_at.desc())
            .first()
        )

        if last_notified and last_notified.notified_at:
            elapsed = (datetime.utcnow() - last_notified.notified_at).total_seconds()
            if elapsed < cooldown_seconds:
                logger.debug(
                    f"[AlertEvaluation] Alert '{alert.name}' cooldown: "
                    f"{elapsed:.0f}s elapsed, need {cooldown_seconds}s"
                )
                return False

        return True

    # ============================================
    # ALERT TRIGGERING
    # ============================================

    def _trigger_alert(
        self,
        alert: Alert,
        triggered_value: float,
        db: Session,
    ) -> Dict[str, Any]:
        """
        Trigger an alert: create history record and send notifications.

        Args:
            alert: Alert ORM object
            triggered_value: The value that triggered the alert
            db: Database session

        Returns:
            Trigger result dict
        """
        triggered_at = datetime.utcnow()

        # Resolve agent names for notification context
        agent_names = None
        if alert.agent_ids:
            agents = (
                db.query(Agent)
                .filter(
                    Agent.id.in_(
                        [
                            UUID(aid) if isinstance(aid, str) else aid
                            for aid in alert.agent_ids
                        ]
                    )
                )
                .all()
            )
            agent_names = [a.name for a in agents]

        # Create AlertHistory record
        history = AlertHistory(
            organization_id=alert.organization_id,
            alert_id=alert.id,
            triggered_at=triggered_at,
            triggered_value=triggered_value,
            threshold_value=alert.threshold_value,
            status=AlertHistoryStatus.TRIGGERED.value,
            context_data={
                "metric_type": alert.metric_type,
                "aggregation": alert.aggregation,
                "operator": alert.operator,
                "time_window_minutes": alert.time_window_minutes,
                "agent_ids": alert.agent_ids,
                "agent_names": agent_names,
            },
        )
        db.add(history)
        db.commit()
        db.refresh(history)

        logger.info(
            f"[AlertEvaluation] Alert '{alert.name}' TRIGGERED: "
            f"value={triggered_value}, threshold={alert.operator} {alert.threshold_value}"
        )

        # Send notifications
        notification_results = alert_notification_service.send_all_notifications(
            alert=alert,
            triggered_value=triggered_value,
            triggered_at=triggered_at,
            agent_names=agent_names,
            history_id=str(history.id),
        )

        # Update history with notification details
        any_success = any(r.get("success") for r in notification_results)
        history.notified_at = datetime.utcnow() if any_success else None
        history.notification_details = {
            "results": notification_results,
            "total_sent": len(notification_results),
            "successful": sum(1 for r in notification_results if r.get("success")),
            "failed": sum(1 for r in notification_results if not r.get("success")),
        }

        if any_success:
            history.status = AlertHistoryStatus.NOTIFIED.value

        db.commit()

        return {
            "alert_id": str(alert.id),
            "alert_name": alert.name,
            "triggered": True,
            "metric_value": triggered_value,
            "threshold": alert.threshold_value,
            "operator": alert.operator,
            "history_id": str(history.id),
            "notifications_sent": len(notification_results),
            "notifications_successful": sum(
                1 for r in notification_results if r.get("success")
            ),
        }


# Singleton instance
alert_evaluation_service = AlertEvaluationService()

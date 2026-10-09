"""Alert evaluation service for checking alert conditions and triggering notifications."""

import operator as op_module
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy import func, and_, text
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
from app.services.alerts.alert_notification_service import (
    alert_notification_service,
    notification_channel_key,
)
from app.services.alerts.production_metrics import (
    compute_production_calls_metric,
    compute_production_traces_metric,
)
from app.models.enums import AlertDataSource


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

OPEN_INCIDENT_STATUSES = (
    AlertHistoryStatus.TRIGGERED.value,
    AlertHistoryStatus.NOTIFIED.value,
    AlertHistoryStatus.ACKNOWLEDGED.value,
)

# Require this many consecutive OK evaluations (Beat runs every 5 min → ~10 min) before
# auto-resolve, so a single borderline metric reading does not close and re-open incidents.
AUTO_RESOLVE_OK_EVALUATIONS = 2
NOTIFICATION_PENDING_MAX_AGE_SECONDS = 600
def _pg_advisory_lock_alert(db: Session, alert_id: UUID) -> None:
    """Serialize incident open/notify for one alert (concurrent eval + manual trigger)."""
    get_bind = getattr(db, "get_bind", None)
    if not callable(get_bind):
        return
    bind = get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return
    key = alert_id.int % (2**31 - 1) or 1
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})


class AlertEvaluationService:
    """Service for evaluating alert conditions against real-time metrics."""

    def evaluate_all_alerts(self, db: Session) -> Dict[str, Any]:
        """
        Evaluate all active alerts across all organizations.
        """
        logger.info("[AlertEvaluation] Starting evaluation of all active alerts")

        from app.core.license import is_feature_enabled

        # Get all active alerts for orgs with alerting entitlement
        active_alerts = [
            alert
            for alert in db.query(Alert)
            .filter(Alert.status == AlertStatus.ACTIVE.value)
            .all()
            if is_feature_enabled("alerts", alert.organization_id)
        ]

        logger.info(f"[AlertEvaluation] Found {len(active_alerts)} active alerts to evaluate")

        results = {
            "total_alerts": len(active_alerts),
            "triggered": 0,
            "not_triggered": 0,
            "errors": 0,
            "skipped_cooldown": 0,
            "new_incidents": 0,
            "ongoing_incidents": 0,
            "auto_resolved": 0,
            "details": [],
        }

        for alert in active_alerts:
            try:
                result = self.evaluate_single_alert(alert, db)
                results["details"].append(result)

                if result.get("triggered"):
                    results["triggered"] += 1
                    if result.get("new_incident"):
                        results["new_incidents"] += 1
                    if result.get("ongoing_incident"):
                        results["ongoing_incidents"] += 1
                    if result.get("skipped_cooldown"):
                        results["skipped_cooldown"] += 1
                else:
                    results["not_triggered"] += 1
                    if result.get("recovered"):
                        results["auto_resolved"] += 1

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

    def evaluate_organization_alerts(
        self, db: Session, organization_id: UUID, *, sync_notifications: bool = False
    ) -> Dict[str, Any]:
        from app.core.license import is_feature_enabled

        if not is_feature_enabled("alerts", organization_id):
            return {"organization_id": str(organization_id), "total_alerts": 0, "skipped": "no_entitlement"}

        active_alerts = (
            db.query(Alert)
            .filter(
                Alert.organization_id == organization_id,
                Alert.status == AlertStatus.ACTIVE.value,
            )
            .all()
        )

        results = {
            "organization_id": str(organization_id),
            "total_alerts": len(active_alerts),
            "triggered": 0,
            "not_triggered": 0,
            "errors": 0,
            "skipped_cooldown": 0,
            "new_incidents": 0,
            "ongoing_incidents": 0,
            "auto_resolved": 0,
            "details": [],
        }

        for alert in active_alerts:
            try:
                result = self.evaluate_single_alert(
                    alert, db, sync_notifications=sync_notifications
                )
                results["details"].append(result)
                if result.get("triggered"):
                    results["triggered"] += 1
                    if result.get("new_incident"):
                        results["new_incidents"] += 1
                    if result.get("ongoing_incident"):
                        results["ongoing_incidents"] += 1
                    if result.get("skipped_cooldown"):
                        results["skipped_cooldown"] += 1
                else:
                    results["not_triggered"] += 1
                    if result.get("recovered"):
                        results["auto_resolved"] += 1
            except Exception as e:
                logger.error(
                    f"[AlertEvaluation] Error evaluating alert '{alert.name}' "
                    f"(id={alert.id}): {e}",
                    exc_info=True,
                )
                results["errors"] += 1
                results["details"].append(
                    {"alert_id": str(alert.id), "alert_name": alert.name, "error": str(e)}
                )
        return results

    def evaluate_single_alert(
        self, alert: Alert, db: Session, *, sync_notifications: bool = False
    ) -> Dict[str, Any]:
        """
        Evaluate a single alert's condition.
        """
        alert_name = alert.name
        logger.debug(f"[AlertEvaluation] Evaluating alert '{alert_name}'")

        db.query(Alert).filter(Alert.id == alert.id).with_for_update().first()

        metric_value = self._compute_metric(alert, db)

        if metric_value is None:
            substituted = self._metric_value_for_missing_data(alert)
            if substituted is not None:
                metric_value = substituted
                logger.debug(
                    f"[AlertEvaluation] Alert '{alert_name}': no data, using {metric_value} (alert_on_missing_data)"
                )
            else:
                logger.debug(
                    f"[AlertEvaluation] Alert '{alert_name}': no data available for metric"
                )
                return {
                    "alert_id": str(alert.id),
                    "alert_name": alert_name,
                    "triggered": False,
                    "metric_value": None,
                    "reason": "No data available for metric computation",
                    "missing_data": True,
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

        if not is_triggered and getattr(alert, "suppress_reopen_until_ok", False):
            alert.suppress_reopen_until_ok = False
            db.commit()

        if is_triggered:
            _pg_advisory_lock_alert(db, alert.id)
            if getattr(alert, "suppress_reopen_until_ok", False):
                logger.info(
                    f"[AlertEvaluation] Alert '{alert_name}': breach suppressed until metric clears"
                )
                return {
                    "alert_id": str(alert.id),
                    "alert_name": alert_name,
                    "triggered": False,
                    "suppressed": True,
                    "metric_value": metric_value,
                    "threshold": threshold,
                    "operator": operator_str,
                    "reason": "Manual resolve: suppressing pages until condition clears",
                }

            open_incidents = self._get_open_incidents(alert.id, db)
            if open_incidents:
                return self._handle_ongoing_incident(
                    alert=alert,
                    incidents=open_incidents,
                    triggered_value=metric_value,
                    db=db,
                    sync_notifications=sync_notifications,
                )
            return self._open_incident(
                alert=alert,
                triggered_value=metric_value,
                db=db,
                send_notifications=True,
                sync_notifications=sync_notifications,
            )

        open_incidents = self._get_open_incidents(alert.id, db)
        if open_incidents:
            return self._handle_condition_cleared(
                alert=alert,
                incidents=open_incidents,
                metric_value=metric_value,
                db=db,
                threshold=threshold,
                operator_str=operator_str,
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

    def _metric_value_for_missing_data(self, alert: Alert) -> Optional[float]:
        if not getattr(alert, "alert_on_missing_data", False):
            return None
        data_source = getattr(alert, "data_source", None) or AlertDataSource.EVALUATIONS.value
        if data_source == AlertDataSource.CRON_JOBS.value:
            return None
        mtype = (alert.metric_type or "").lower()
        volume_metrics = {
            AlertMetricType.NUMBER_OF_CALLS.value,
            "number_of_calls",
            AlertMetricType.CUSTOM.value,
            "custom",
        }
        if mtype in volume_metrics:
            return 0.0
        return None

    def _compute_metric(
        self, alert: Alert, db: Session
    ) -> Optional[float]:
        """
        Compute the aggregated metric value for an alert.
        """
        metric_type = alert.metric_type
        aggregation = alert.aggregation
        time_window = alert.time_window_minutes
        organization_id = alert.organization_id
        agent_ids = alert.agent_ids  # JSON list of agent UUID strings, or None
        data_source = getattr(alert, "data_source", None) or AlertDataSource.EVALUATIONS.value

        now = datetime.now(timezone.utc)
        window_start = now - timedelta(minutes=time_window)

        if data_source == AlertDataSource.PRODUCTION_CALLS.value:
            return compute_production_calls_metric(
                db,
                organization_id,
                agent_ids,
                window_start,
                metric_type,
                aggregation,
            )
        if data_source == AlertDataSource.PRODUCTION_TRACES.value:
            return compute_production_traces_metric(
                organization_id,
                agent_ids,
                window_start,
                metric_type,
                aggregation,
            )
        if data_source == AlertDataSource.CRON_JOBS.value:
            from app.services.alerts.cron_metrics import compute_cron_jobs_metric

            return compute_cron_jobs_metric(
                db, organization_id, metric_type, window_start
            )

        # Route to the appropriate metric calculator (evaluations)
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

    def _get_open_incidents(self, alert_id: UUID, db: Session) -> List[AlertHistory]:
        return (
            db.query(AlertHistory)
            .filter(
                and_(
                    AlertHistory.alert_id == alert_id,
                    AlertHistory.status.in_(OPEN_INCIDENT_STATUSES),
                )
            )
            .order_by(AlertHistory.triggered_at.desc())
            .with_for_update()
            .all()
        )

    def _should_notify_for_incident(self, alert: Alert, incident: AlertHistory) -> bool:
        """
        Whether to send (or re-send) notifications for an open incident.
        Immediate = notify only when the incident opens (not on every eval).
        """
        frequency = alert.notify_frequency
        cooldown_seconds = FREQUENCY_COOLDOWN.get(frequency, 0)

        if self._notification_reservation_active(incident):
            return False

        if cooldown_seconds == 0:
            if incident.status in (
                AlertHistoryStatus.NOTIFIED.value,
                AlertHistoryStatus.ACKNOWLEDGED.value,
            ):
                return False
            if incident.notified_at is not None:
                return False
            return incident.status == AlertHistoryStatus.TRIGGERED.value

        if incident.notified_at is None:
            return True

        notified_at = incident.notified_at
        if notified_at.tzinfo is None:
            notified_at = notified_at.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - notified_at).total_seconds()
        if elapsed < cooldown_seconds:
            logger.debug(
                f"[AlertEvaluation] Alert '{alert.name}' cooldown: "
                f"{elapsed:.0f}s elapsed, need {cooldown_seconds}s"
            )
            return False
        return True

    def _notification_reservation_active(self, incident: AlertHistory) -> bool:
        ctx = incident.context_data or {}
        if not ctx.get("notification_delivery_pending"):
            return False
        raw = ctx.get("notification_delivery_pending_at")
        if not raw:
            return False
        try:
            started = datetime.fromisoformat(str(raw))
        except ValueError:
            return False
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - started).total_seconds()
        return age < NOTIFICATION_PENDING_MAX_AGE_SECONDS

    def _clear_notification_reservation(self, history: AlertHistory) -> None:
        ctx = dict(history.context_data or {})
        ctx.pop("notification_delivery_pending", None)
        ctx.pop("notification_delivery_pending_at", None)
        history.context_data = ctx

    def _merge_context(self, history: AlertHistory, **extra: Any) -> None:
        ctx = dict(history.context_data or {})
        ctx.update(extra)
        history.context_data = ctx

    def _handle_ongoing_incident(
        self,
        alert: Alert,
        incidents: List[AlertHistory],
        triggered_value: float,
        db: Session,
        *,
        sync_notifications: bool = False,
    ) -> Dict[str, Any]:
        primary = incidents[0]
        for stale in incidents[1:]:
            self._auto_resolve_incident(
                stale,
                alert,
                triggered_value,
                db,
                note="Auto-resolved: superseded by a newer open incident for this alert.",
            )

        primary.triggered_value = triggered_value
        self._merge_context(
            primary,
            last_evaluated_at=datetime.now(timezone.utc).isoformat(),
            in_alarm=True,
            ok_evaluation_streak=0,
        )
        db.commit()

        send_notifications = self._should_notify_for_incident(alert, primary)
        notification_results: List[Dict[str, Any]] = []
        if send_notifications:
            notification_results = self._send_notifications(
                alert,
                primary,
                triggered_value,
                db,
                sync=sync_notifications,
            )
        else:
            logger.info(
                f"[AlertEvaluation] Alert '{alert.name}' ongoing incident "
                f"(history_id={primary.id}): skipping notification "
                f"(frequency={alert.notify_frequency})"
            )

        return {
            "alert_id": str(alert.id),
            "alert_name": alert.name,
            "triggered": True,
            "ongoing_incident": True,
            "new_incident": False,
            "metric_value": triggered_value,
            "threshold": alert.threshold_value,
            "operator": alert.operator,
            "history_id": str(primary.id),
            "skipped_cooldown": not send_notifications,
            "notifications_sent": len(notification_results),
            "notifications_successful": sum(
                1 for r in notification_results if r.get("success")
            ),
        }

    def _handle_condition_cleared(
        self,
        alert: Alert,
        incidents: List[AlertHistory],
        metric_value: float,
        db: Session,
        *,
        threshold: float,
        operator_str: str,
    ) -> Dict[str, Any]:
        resolved_ids: List[str] = []
        max_streak = 0
        for incident in incidents:
            ctx = dict(incident.context_data or {})
            streak = int(ctx.get("ok_evaluation_streak", 0)) + 1
            max_streak = max(max_streak, streak)
            ctx["ok_evaluation_streak"] = streak
            ctx["last_ok_metric_value"] = metric_value
            incident.context_data = ctx

            if streak >= AUTO_RESOLVE_OK_EVALUATIONS:
                self._auto_resolve_incident(
                    incident, alert, metric_value, db, send_recovery=True
                )
                resolved_ids.append(str(incident.id))
            else:
                db.commit()
                logger.info(
                    f"[AlertEvaluation] Alert '{alert.name}' condition cleared "
                    f"({metric_value} {operator_str} {threshold}): "
                    f"OK streak {streak}/{AUTO_RESOLVE_OK_EVALUATIONS}, incident stays open"
                )

        if resolved_ids:
            logger.info(
                f"[AlertEvaluation] Alert '{alert.name}' recovered: "
                f"auto-resolved {len(resolved_ids)} incident(s)"
            )
            return {
                "alert_id": str(alert.id),
                "alert_name": alert.name,
                "triggered": False,
                "recovered": True,
                "metric_value": metric_value,
                "threshold": threshold,
                "operator": operator_str,
                "history_ids": resolved_ids,
            }

        return {
            "alert_id": str(alert.id),
            "alert_name": alert.name,
            "triggered": False,
            "recovering": True,
            "metric_value": metric_value,
            "threshold": threshold,
            "operator": operator_str,
            "ok_evaluation_streak": max_streak,
            "ok_evaluations_needed": AUTO_RESOLVE_OK_EVALUATIONS,
        }

    def _auto_resolve_incident(
        self,
        history: AlertHistory,
        alert: Alert,
        metric_value: float,
        db: Session,
        *,
        note: Optional[str] = None,
        send_recovery: bool = False,
    ) -> None:
        now = datetime.now(timezone.utc)
        history.status = AlertHistoryStatus.RESOLVED.value
        history.resolved_at = now
        history.resolved_by = "system"
        if note:
            history.resolution_notes = note
        elif not history.resolution_notes:
            history.resolution_notes = (
                f"Auto-resolved: condition cleared ({metric_value} vs "
                f"{alert.operator} {alert.threshold_value})."
            )
        self._merge_context(
            history,
            last_metric_value=metric_value,
            auto_resolved=True,
            recovered_at=now.isoformat(),
        )
        db.commit()
        if send_recovery:
            from app.services.alerts.alerting_settings import is_lifecycle_sync_enabled

            if is_lifecycle_sync_enabled(alert.organization_id, db):
                recovery_results = alert_notification_service.send_recovery_notifications(
                    alert,
                    history_id=str(history.id),
                    metric_value=metric_value,
                )
                details = dict(history.notification_details or {})
                lifecycle = dict(details.get("lifecycle") or {})
                lifecycle["recovery"] = recovery_results
                details["lifecycle"] = lifecycle
                history.notification_details = details
                db.commit()

    # ============================================
    # ALERT TRIGGERING
    # ============================================

    def _open_incident(
        self,
        alert: Alert,
        triggered_value: float,
        db: Session,
        *,
        send_notifications: bool = True,
        sync_notifications: bool = False,
    ) -> Dict[str, Any]:
        """
        Open a new incident: one history row per breach cycle (OK → ALARM).
        """
        existing = self._get_open_incidents(alert.id, db)
        if existing:
            return self._handle_ongoing_incident(
                alert=alert,
                incidents=existing,
                triggered_value=triggered_value,
                db=db,
                sync_notifications=sync_notifications,
            )

        triggered_at = datetime.now(timezone.utc)

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
                "data_source": getattr(alert, "data_source", None) or "evaluations",
                "metric_type": alert.metric_type,
                "aggregation": alert.aggregation,
                "operator": alert.operator,
                "time_window_minutes": alert.time_window_minutes,
                "agent_ids": alert.agent_ids,
                "agent_names": agent_names,
            },
        )
        self._merge_context(history, in_alarm=True)
        db.add(history)
        db.commit()
        db.refresh(history)

        logger.info(
            f"[AlertEvaluation] Alert '{alert.name}' OPENED incident: "
            f"value={triggered_value}, threshold={alert.operator} {alert.threshold_value}"
        )

        notification_results: List[Dict[str, Any]] = []
        if send_notifications:
            notification_results = self._send_notifications(
                alert,
                history,
                triggered_value,
                db,
                sync=sync_notifications,
            )
        else:
            history.notification_details = {
                "results": [],
                "total_sent": 0,
                "successful": 0,
                "failed": 0,
                "skipped_reason": "notifications_disabled",
            }
            db.commit()

        return {
            "alert_id": str(alert.id),
            "alert_name": alert.name,
            "triggered": True,
            "new_incident": True,
            "ongoing_incident": False,
            "metric_value": triggered_value,
            "threshold": alert.threshold_value,
            "operator": alert.operator,
            "history_id": str(history.id),
            "skipped_cooldown": not send_notifications,
            "notifications_sent": len(notification_results),
            "notifications_successful": sum(
                1 for r in notification_results if r.get("success")
            ),
        }

    def deliver_notifications_for_history(
        self,
        alert: Alert,
        history: AlertHistory,
        triggered_value: float,
        db: Session,
    ) -> List[Dict[str, Any]]:
        return self._deliver_notifications(alert, history, triggered_value, db)

    def _send_notifications(
        self,
        alert: Alert,
        history: AlertHistory,
        triggered_value: float,
        db: Session,
        *,
        sync: bool,
    ) -> List[Dict[str, Any]]:
        if sync:
            return self._deliver_notifications(alert, history, triggered_value, db)

        db.refresh(history)
        if not self._should_notify_for_incident(alert, history):
            return []

        self._merge_context(
            history,
            notification_delivery_pending=True,
            notification_delivery_pending_at=datetime.now(timezone.utc).isoformat(),
        )
        db.commit()

        from app.workers.tasks.send_alert_notifications import send_alert_notifications_task

        try:
            send_alert_notifications_task.delay(
                str(alert.id),
                str(history.id),
                triggered_value,
            )
        except Exception as exc:
            logger.warning(
                f"[AlertEvaluation] Failed to queue notification for history {history.id}: {exc}"
            )
            db.refresh(history)
            self._clear_notification_reservation(history)
            db.commit()
        return []

    def _deliver_notifications(
        self,
        alert: Alert,
        history: AlertHistory,
        triggered_value: float,
        db: Session,
    ) -> List[Dict[str, Any]]:
        db.refresh(history)
        if history.status not in OPEN_INCIDENT_STATUSES:
            self._clear_notification_reservation(history)
            db.commit()
            return []
        self._clear_notification_reservation(history)
        if not self._should_notify_for_incident(alert, history):
            db.commit()
            return []

        agent_names = (history.context_data or {}).get("agent_names")
        triggered_at = history.triggered_at
        if triggered_at and triggered_at.tzinfo is None:
            triggered_at = triggered_at.replace(tzinfo=timezone.utc)
        elif triggered_at is None:
            triggered_at = datetime.now(timezone.utc)

        ctx = dict(history.context_data or {})
        cooldown_seconds = FREQUENCY_COOLDOWN.get(alert.notify_frequency, 0)
        if cooldown_seconds > 0 and history.notified_at is not None:
            ctx.pop("notified_channel_keys", None)
        already = set(ctx.get("notified_channel_keys") or [])
        notification_results = alert_notification_service.send_all_notifications(
            alert=alert,
            triggered_value=triggered_value,
            triggered_at=triggered_at,
            agent_names=agent_names,
            history_id=str(history.id),
            skip_channel_keys=already,
        )

        succeeded = set(already)
        pending_failure = False
        for result in notification_results:
            if result.get("success"):
                succeeded.add(notification_channel_key(result))
            else:
                pending_failure = True
        if pending_failure:
            ctx["notified_channel_keys"] = sorted(succeeded)
        else:
            ctx.pop("notified_channel_keys", None)
        history.context_data = ctx
        all_delivered = bool(notification_results) and not pending_failure
        history.notified_at = datetime.now(timezone.utc) if all_delivered else None
        history.notification_details = {
            "results": notification_results,
            "total_sent": len(notification_results),
            "successful": sum(1 for r in notification_results if r.get("success")),
            "failed": sum(1 for r in notification_results if not r.get("success")),
        }
        if all_delivered and history.status == AlertHistoryStatus.TRIGGERED.value:
            history.status = AlertHistoryStatus.NOTIFIED.value
        db.commit()
        return notification_results


# Singleton instance
alert_evaluation_service = AlertEvaluationService()

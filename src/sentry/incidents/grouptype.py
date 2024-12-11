from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sentry import features
from sentry.incidents.endpoints.validators import MetricAlertsDetectorValidator
from sentry.incidents.utils.types import QuerySubscriptionUpdate
from sentry.issues.grouptype import GroupCategory, GroupType
from sentry.issues.issue_occurrence import IssueOccurrence
from sentry.models.organization import Organization
from sentry.ratelimits.sliding_windows import Quota
from sentry.types.group import PriorityLevel
from sentry.workflow_engine.handlers.detector import (
    DetectorEvaluationResult,
    StatefulDetectorHandler,
)
from sentry.workflow_engine.models.data_source import DataPacket
from sentry.workflow_engine.types import DetectorPriorityLevel


class MetricAlertDetectorHandler(StatefulDetectorHandler[QuerySubscriptionUpdate]):
    def evaluate(
        self,
        data_packet: DataPacket[QuerySubscriptionUpdate],
    ) -> dict[str | None, DetectorEvaluationResult]:
        # TODO - Don't override this method, instead use the StatefulDetectorHandler's evaluate method and data_conditions
        occurrence, event_data = self.build_occurrence_and_event_data("foo", 0, PriorityLevel.HIGH)

        return {
            "foo": DetectorEvaluationResult(
                is_active=True,
                group_key="foo",
                priority=DetectorPriorityLevel.HIGH,
                result=occurrence,
                event_data=event_data,
            )
        }

    def build_occurrence_and_event_data(
        self, group_key: str | None, value: int, new_status: PriorityLevel
    ) -> tuple[IssueOccurrence, dict[str, Any]]:
        # placeholder return for now
        occurrence = IssueOccurrence(
            id="eb4b0acffadb4d098d48cb14165ab578",
            project_id=123,
            event_id="43878ab4419f4ab181f6379ac376d5aa",
            fingerprint=["abc123"],
            issue_title="Some Issue",
            subtitle="Some subtitle",
            resource_id=None,
            evidence_data={},
            evidence_display=[],
            type=MetricAlertFire,
            detection_time=datetime.now(timezone.utc),
            level="error",
            culprit="Some culprit",
            initial_issue_priority=new_status.value,
        )
        event_data = {
            "timestamp": occurrence.detection_time,
            "project_id": occurrence.project_id,
            "event_id": occurrence.event_id,
            "platform": "python",
            "received": occurrence.detection_time,
            "tags": {},
        }
        return occurrence, event_data

    @property
    def counter_names(self) -> list[str]:
        return []  # placeholder return for now

    def get_dedupe_value(self, data_packet: DataPacket[QuerySubscriptionUpdate]) -> int:
        return 0  # placeholder return for now

    def get_group_key_values(
        self, data_packet: DataPacket[QuerySubscriptionUpdate]
    ) -> dict[str, int]:
        return {"foo": 0}


# Example GroupType and detector handler for metric alerts. We don't create these issues yet, but we'll use something
# like these when we're sending issues as alerts
@dataclass(frozen=True)
class MetricAlertFire(GroupType):
    type_id = 8001
    slug = "metric_alert_fire"
    description = "Metric alert fired"
    category = GroupCategory.METRIC_ALERT.value
    creation_quota = Quota(3600, 60, 100)
    default_priority = PriorityLevel.HIGH
    enable_auto_resolve = False
    enable_escalation_detection = False
    detector_handler = MetricAlertDetectorHandler
    detector_validator = MetricAlertsDetectorValidator
    detector_config_schema = {}  # TODO(colleen): update this

    @classmethod
    def allow_post_process_group(cls, organization: Organization) -> bool:
        return features.has("organizations:workflow-engine-metric-alert-processing", organization)

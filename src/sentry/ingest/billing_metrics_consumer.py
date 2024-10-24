import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, cast

import orjson
from arroyo.backends.kafka import KafkaPayload
from arroyo.processing.strategies import (
    CommitOffsets,
    ProcessingStrategy,
    ProcessingStrategyFactory,
)
from arroyo.types import Commit, Message, Partition
from django.core.cache import cache
from sentry_kafka_schemas.schema_types.snuba_generic_metrics_v1 import GenericMetric

from sentry import options
from sentry.constants import DataCategory
from sentry.models.project import Project
from sentry.sentry_metrics.indexer.strings import SPAN_METRICS_NAMES, TRANSACTION_METRICS_NAMES
from sentry.sentry_metrics.use_case_id_registry import UseCaseID
from sentry.signals import first_custom_metric_received
from sentry.snuba.metrics import parse_mri
from sentry.snuba.metrics.naming_layer.mri import is_custom_metric
from sentry.utils.outcomes import Outcome, track_outcome

logger = logging.getLogger(__name__)

# 7 days of TTL.
CACHE_TTL_IN_SECONDS = 60 * 60 * 24 * 7


def _get_project_flag_updated_cache_key(org_id: int, project_id: int) -> str:
    return f"has-custom-metrics-flag-updated:{org_id}:{project_id}"


class BillingMetricsConsumerStrategyFactory(ProcessingStrategyFactory[KafkaPayload]):
    def create_with_partitions(
        self,
        commit: Commit,
        partitions: Mapping[Partition, int],
    ) -> ProcessingStrategy[KafkaPayload]:
        return BillingTxCountMetricConsumerStrategy(CommitOffsets(commit))


class BillingTxCountMetricConsumerStrategy(ProcessingStrategy[KafkaPayload]):
    """A metrics consumer that generates a billing outcome for each processed
    transaction, processing a bucket at a time. The transaction count is
    directly taken from the `c:transactions/usage@none` counter metric.
    """

    #: The IDs of the metrics used to count transactions or spans
    metric_ids = {
        TRANSACTION_METRICS_NAMES["c:transactions/usage@none"]: (
            UseCaseID.TRANSACTIONS,
            DataCategory.TRANSACTION,
        ),
        SPAN_METRICS_NAMES["c:spans/usage@none"]: (UseCaseID.SPANS, DataCategory.SPAN),
    }

    def __init__(self, next_step: ProcessingStrategy[Any]) -> None:
        self.__next_step = next_step
        self.__closed = False

    def poll(self) -> None:
        self.__next_step.poll()

    def terminate(self) -> None:
        self.close()

    def close(self) -> None:
        self.__closed = True
        self.__next_step.close()

    def submit(self, message: Message[KafkaPayload]) -> None:
        assert not self.__closed

        payload = self._get_payload(message)

        self._produce_billing_outcomes(payload)
        self._flag_metric_received_for_project(payload)

        self.__next_step.submit(message)

    def _get_payload(self, message: Message[KafkaPayload]) -> GenericMetric:
        payload = orjson.loads(message.payload.value)
        return cast(GenericMetric, payload)

    def _count_processed_items(self, generic_metric: GenericMetric) -> Mapping[DataCategory, int]:
        metric_id = generic_metric["metric_id"]
        try:
            data_category = self.metric_ids[metric_id]
        except KeyError:
            return {}

        # In the new world, if we are see a usage metric which has the `indexed` tag set to `true` it means that an
        # indexed payload was supposed to be received and counted by the respective consumer, so we will not count it
        # here to avoid double counting.
        if options.get("consumers.use_new_counting_strategy") and self._has_indexed(generic_metric):
            return {}

        value = generic_metric["value"]
        try:
            quantity = max(int(value), 0)  # type: ignore[arg-type]
        except TypeError:
            # Unexpected value type for this metric ID, skip.
            return {}

        items = {data_category: quantity}

        if self._has_profile(generic_metric):
            # The bucket is tagged with the "has_profile" tag,
            # so we also count the quantity of this bucket towards profiles.
            # This assumes a "1 to 0..1" relationship between transactions / spans and profiles.
            items[DataCategory.PROFILE] = quantity

        return items

    def _has_profile(self, generic_metric: GenericMetric) -> bool:
        return self._has_tag(generic_metric, "has_profile")

    def _has_indexed(self, generic_metric: GenericMetric) -> bool:
        return self._has_tag(generic_metric, "indexed")

    def _has_tag(self, generic_metric: GenericMetric, tag_key: str) -> bool:
        indexed_tag_key = self._resolve(generic_metric, tag_key)
        if indexed_tag_key is None:
            return False

        tag_value = generic_metric["tags"].get(indexed_tag_key)
        return tag_value == "true"

    def _produce_billing_outcomes(self, generic_metric: GenericMetric) -> None:
        for category, quantity in self._count_processed_items(generic_metric).items():
            self._produce_billing_outcome(
                org_id=generic_metric["org_id"],
                project_id=generic_metric["project_id"],
                category=category,
                quantity=quantity,
            )

    def _produce_billing_outcome(
        self, *, org_id: int, project_id: int, category: DataCategory, quantity: int
    ) -> None:
        if quantity < 1:
            return

        # track_outcome does not guarantee to deliver the outcome, making this
        # an at-most-once delivery.
        #
        # If it turns out that we drop too many outcomes on shutdown,
        # we may have to revisit this part to achieve a
        # better approximation of exactly-once delivery.
        track_outcome(
            org_id=org_id,
            project_id=project_id,
            key_id=None,
            outcome=Outcome.ACCEPTED,
            reason=None,
            timestamp=datetime.now(timezone.utc),
            event_id=None,
            category=category,
            quantity=quantity,
        )

    def _flag_metric_received_for_project(self, generic_metric: GenericMetric) -> None:
        try:
            org_id = generic_metric["org_id"]
            project_id = generic_metric["project_id"]
            metric_mri = self._reverse_resolve(generic_metric, generic_metric["metric_id"])

            parsed_mri = parse_mri(metric_mri)
            if parsed_mri is None or not is_custom_metric(parsed_mri):
                return

            # If the cache key is present, it means that we have already updated the metric flag for this project.
            cache_key = _get_project_flag_updated_cache_key(org_id, project_id)
            if cache.get(cache_key) is not None:
                return

            project = Project.objects.get_from_cache(id=project_id)

            if not project.flags.has_custom_metrics:
                first_custom_metric_received.send_robust(project=project, sender=project)

            cache.set(cache_key, "1", CACHE_TTL_IN_SECONDS)
        except Project.DoesNotExist:
            pass

    def _resolve(self, generic_metric: GenericMetric, value: str) -> str | None:
        """
        Resolves the original string value of a field to its indexed value.

        The resolution leverages the `mapping_meta` field of the generic metric payload.
        """
        mapping_meta = generic_metric["mapping_meta"]
        for _, inner_meta in mapping_meta.items():
            for indexed_value, original_value in inner_meta.items():
                if original_value == value:
                    return indexed_value

        return None

    def _reverse_resolve(self, generic_metric: GenericMetric, indexed_value: int) -> str | None:
        """
        Reverse resolves the indexed value in the metric payload to the original string value.

        The resolution leverages the `mapping_meta` field of the generic metric payload.
        """
        mapping_meta = generic_metric["mapping_meta"]
        for _, inner_meta in mapping_meta.items():
            if (string_value := inner_meta.get(str(indexed_value))) is not None:
                return string_value

        return None

    def join(self, timeout: float | None = None) -> None:
        self.__next_step.join(timeout)

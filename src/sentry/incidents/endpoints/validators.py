from collections.abc import Sequence
from datetime import timedelta

from rest_framework import serializers

from sentry.api.serializers.rest_framework import EnvironmentField
from sentry.incidents.utils.constants import INCIDENTS_SNUBA_SUBSCRIPTION_TYPE
from sentry.snuba.dataset import Dataset
from sentry.snuba.models import (
    QuerySubscription,
    QuerySubscriptionDataSourceHandler,
    SnubaQuery,
    SnubaQueryEventType,
)
from sentry.snuba.subscriptions import (
    create_snuba_query,
    create_snuba_subscription,
    update_snuba_query,
)
from sentry.workflow_engine.endpoints.validators.base import (
    BaseDataSourceValidator,
    BaseGroupTypeDetectorValidator,
    NumericComparisonConditionValidator,
)
from sentry.workflow_engine.models.data_condition import Condition, DataCondition
from sentry.workflow_engine.models.data_condition_group import DataConditionGroup
from sentry.workflow_engine.models.data_source import DataSource
from sentry.workflow_engine.types import DetectorPriorityLevel


class SnubaQueryDataSourceValidator(BaseDataSourceValidator[QuerySubscription]):
    query_type = serializers.IntegerField(required=True)
    dataset = serializers.CharField(required=True)
    query = serializers.CharField(required=True)
    aggregate = serializers.CharField(required=True)
    time_window = serializers.IntegerField(required=True)
    environment = EnvironmentField(required=True, allow_null=True)
    event_types = serializers.ListField(
        child=serializers.IntegerField(),
    )

    data_source_type_handler = QuerySubscriptionDataSourceHandler

    def validate_query_type(self, value: int) -> SnubaQuery.Type:
        try:
            return SnubaQuery.Type(value)
        except ValueError:
            raise serializers.ValidationError(f"Invalid query type {value}")

    def validate_dataset(self, value: str) -> Dataset:
        try:
            return Dataset(value)
        except ValueError:
            raise serializers.ValidationError(
                f"Invalid dataset {value}. Must be one of: {', '.join(Dataset.__members__)}"
            )

    def validate_event_types(self, value: Sequence[int]) -> list[SnubaQueryEventType.EventType]:
        try:
            return [SnubaQueryEventType.EventType(t) for t in value]
        except ValueError:
            raise serializers.ValidationError(f"Invalid event type: {value}")

    def validate_time_window(self, value: int) -> timedelta:
        return timedelta(minutes=value)

    def create_source(self, validated_data) -> QuerySubscription:
        snuba_query = create_snuba_query(
            query_type=validated_data["query_type"],
            dataset=validated_data["dataset"],
            query=validated_data["query"],
            aggregate=validated_data["aggregate"],
            time_window=validated_data["time_window"],
            # TODO: Feed the usual metric alerts logic in here based on time window
            resolution=timedelta(minutes=1),
            environment=validated_data["environment"],
            event_types=validated_data["event_types"],
        )
        return create_snuba_subscription(
            project=self.context["project"],
            subscription_type=INCIDENTS_SNUBA_SUBSCRIPTION_TYPE,
            snuba_query=snuba_query,
        )


class MetricAlertComparisonConditionValidator(NumericComparisonConditionValidator):
    """
    Implementation note:
    This is just a reference for how to use these validators and a basic implementation for the
    metric alert conditions. Note that these shouldn't exist in this file long term - these are
    implementations, and so should be implemented in `incidents` project (or wherever we decide
    metric alerts live in the future).
    Only generic workflow code should live here
    """

    supported_conditions = frozenset((Condition.GREATER, Condition.LESS))
    supported_results = frozenset((DetectorPriorityLevel.HIGH, DetectorPriorityLevel.MEDIUM))


class MetricAlertsDetectorValidator(BaseGroupTypeDetectorValidator):
    data_source = SnubaQueryDataSourceValidator(required=True, many=True)
    data_conditions = MetricAlertComparisonConditionValidator()

    def validate(self, attrs):
        """
        This is just a sample implementation. We should have all the same logic here that
        we have for conditions, query validation, etc in
        https://github.com/getsentry/sentry/blob/837d5c1e13a8dc71b622aafec5191d84d0e827c7/src/sentry/incidents/serializers/alert_rule.py#L65
        And this should be moved to a metric alert specific app, probably `incidents/`
        """
        attrs = super().validate(attrs)
        # TODO should we limit the number of data sources?
        return attrs

    def update_data_condition(self, instance, data_conditions):
        """
        Update the data condition if it already exists, create one if it does not
        """
        if instance.workflow_condition_group:
            try:
                data_condition = DataCondition.objects.get(
                    condition_group=instance.workflow_condition_group
                )
            except DataCondition.DoesNotExist:
                raise serializers.ValidationError("DataCondition not found, can't update")

            # XXX: tests pass 'result' rather than 'condition_result' and it's checked by the NumericComparisonConditionValidator
            updated_values = {
                "type": data_conditions.get("type", data_condition.type),
                "comparison": data_conditions.get("comparison", data_condition.comparison),
                "condition_result": data_conditions.get("result", data_condition.condition_result),
            }
            data_condition.update(**updated_values)
            return instance.workflow_condition_group

        condition_group = DataConditionGroup.objects.create(
            logic_type=DataConditionGroup.Type.ANY,
            organization_id=self.context["organization"].id,
        )
        DataCondition.objects.create(
            type=data_condition.get("type"),
            comparison=data_condition.get("comparison"),
            condition_result=data_condition.get("result"),
            condition_group=condition_group,
        )
        return condition_group

    def update_data_source(self, instance, data_source):
        for source in data_source:
            try:
                source_instance = DataSource.objects.get(detector=instance)
            except DataSource.DoesNotExist:
                continue
            if source_instance:
                try:
                    snuba_query = SnubaQuery.objects.get(id=source_instance.query_id)
                except SnubaQuery.DoesNotExist:
                    raise serializers.ValidationError("SnubaQuery not found, can't update")

            event_types = SnubaQueryEventType.objects.filter(snuba_query_id=snuba_query.id)
            update_snuba_query(
                snuba_query=snuba_query,
                query_type=source.get("query_type", snuba_query.type),
                dataset=source.get("dataset", snuba_query.dataset),
                query=source.get("query", snuba_query.query),
                aggregate=source.get("aggregate", snuba_query.aggregate),
                time_window=source.get("time_window", timedelta(seconds=snuba_query.time_window)),
                resolution=timedelta(seconds=source.get("resolution", snuba_query.resolution)),
                environment=source.get("environment", snuba_query.environment),
                event_types=source.get("event_types", [event_types]),
            )
            # TODO handle adding an additional DataSource

    def update(self, instance, validated_data):
        instance.name = validated_data.get("name", instance.name)
        instance.type = validated_data.get("group_type", instance.group_type).slug
        data_conditions = validated_data.pop(
            "data_conditions"
        )  # TODO this is not a m2m, should be updated to data_condition singular
        if data_conditions:
            instance.workflow_condition_group = self.update_data_condition(
                instance, data_conditions
            )
        # TODO check if DCG logic_type needs to be updated ?

        data_source = validated_data.pop(
            "data_source"
        )  # TODO this IS a m2m, should be updated to data_sources plural
        if data_source:
            self.update_data_source(instance, data_source)

        instance.save()
        return instance

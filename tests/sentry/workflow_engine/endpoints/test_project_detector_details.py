from datetime import timedelta

import pytest

from sentry.api.serializers import serialize
from sentry.incidents.grouptype import MetricAlertFire
from sentry.incidents.utils.constants import INCIDENTS_SNUBA_SUBSCRIPTION_TYPE
from sentry.snuba.dataset import Dataset
from sentry.snuba.models import SnubaQuery, SnubaQueryEventType
from sentry.snuba.subscriptions import create_snuba_query, create_snuba_subscription
from sentry.testutils.cases import APITestCase
from sentry.testutils.silo import region_silo_test
from sentry.workflow_engine.models import (
    DataCondition,
    DataConditionGroup,
    DataSource,
    DataSourceDetector,
    Detector,
)
from sentry.workflow_engine.models.data_condition import Condition
from sentry.workflow_engine.types import DetectorPriorityLevel


@pytest.mark.snuba_ci
class ProjectDetectorDetailsBaseTest(APITestCase):
    endpoint = "sentry-api-0-project-detector-details"

    def setUp(self):
        super().setUp()
        self.login_as(user=self.user)
        self.environment = self.create_environment(
            organization_id=self.organization.id, name="production"
        )
        with self.tasks():
            self.snuba_query = create_snuba_query(
                query_type=SnubaQuery.Type.ERROR,
                dataset=Dataset.Events,
                query="hello",
                aggregate="count()",
                time_window=timedelta(minutes=1),
                resolution=timedelta(minutes=1),
                environment=self.environment,
                event_types=[SnubaQueryEventType.EventType.ERROR],
            )
            self.query_subscription = create_snuba_subscription(
                project=self.project,
                subscription_type=INCIDENTS_SNUBA_SUBSCRIPTION_TYPE,
                snuba_query=self.snuba_query,
            )
        self.data_source = self.create_data_source(
            organization=self.organization, query_id=self.query_subscription.id
        )
        self.condition_group = self.create_data_condition_group(
            organization_id=self.organization.id,
            logic_type=DataConditionGroup.Type.ANY,
        )
        self.condition = self.create_data_condition(
            condition_group=self.condition_group,
            type=Condition.LESS,
            comparison=50,
            condition_result=DetectorPriorityLevel.LOW,
        )
        self.detector = self.create_detector(
            project_id=self.project.id,
            name="Test Detector",
            type=MetricAlertFire.slug,
            workflow_condition_group=self.condition_group,
        )
        DataSourceDetector.objects.create(data_source=self.data_source, detector=self.detector)
        assert self.detector.data_sources is not None


@region_silo_test
class ProjectDetectorDetailsGetTest(ProjectDetectorDetailsBaseTest):
    def test_simple(self):
        response = self.get_success_response(
            self.organization.slug, self.project.slug, self.detector.id
        )
        assert response.data == serialize(self.detector)

    def test_does_not_exist(self):
        self.get_error_response(self.organization.slug, self.project.slug, 3, status_code=404)


@region_silo_test
class ProjectDetectorDetailsPutTest(ProjectDetectorDetailsBaseTest):
    method = "PUT"

    def setUp(self):
        super().setUp()
        self.valid_data = {
            "name": "Updated Detector",
            "group_type": MetricAlertFire.slug,
            "data_source": [
                {
                    "query_type": self.snuba_query.type,
                    "dataset": self.snuba_query.dataset,
                    "query": "updated query",
                    "aggregate": self.snuba_query.aggregate,
                    "time_window": 5,  # minutes
                    "environment": None,  # getting env not in org error when passing self.environment.id
                    "event_types": [
                        event_type.value for event_type in self.snuba_query.event_types
                    ],
                }
            ],
            "data_conditions": [
                {
                    "id": self.condition.id,
                    "type": Condition.GREATER,
                    "comparison": 100,
                    "result": DetectorPriorityLevel.HIGH,
                }
            ],
        }

    def test_update(self):
        with self.tasks():
            response = self.get_success_response(
                self.organization.slug,
                self.project.slug,
                self.detector.id,
                **self.valid_data,
                status_code=200,
            )

        detector = Detector.objects.get(id=response.data["id"])
        assert response.data == serialize([detector])[0]
        assert detector.name == "Updated Detector"
        assert detector.type == MetricAlertFire.slug
        assert detector.project_id == self.project.id

        condition_group = detector.workflow_condition_group
        assert condition_group
        assert condition_group.logic_type == DataConditionGroup.Type.ANY
        assert condition_group.organization_id == self.organization.id

        conditions = list(DataCondition.objects.filter(condition_group=condition_group))
        assert len(conditions) == 1
        condition = conditions[0]
        assert condition.type == Condition.GREATER
        assert condition.comparison == 100
        assert condition.condition_result == DetectorPriorityLevel.HIGH

        data_source_detector = DataSourceDetector.objects.get(detector=detector)
        data_source = DataSource.objects.get(id=data_source_detector.detector.id)
        snuba_query = SnubaQuery.objects.get(id=data_source.query_id)
        assert snuba_query.query == "updated query"
        assert snuba_query.time_window == 300  # seconds = 5 minutes

    def test_update_missing_data_condition(self):
        """
        Edge case - ensure we raise if the DataCondition can't be found
        """
        DataCondition.objects.get(id=self.condition.id).delete()
        with self.tasks():
            self.get_error_response(
                self.organization.slug,
                self.project.slug,
                self.detector.id,
                **self.valid_data,
                status_code=400,
            )

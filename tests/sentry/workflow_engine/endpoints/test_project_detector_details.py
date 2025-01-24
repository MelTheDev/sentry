from sentry.api.serializers import serialize
from sentry.incidents.grouptype import MetricAlertFire

# from sentry.snuba.dataset import Dataset
# from sentry.snuba.models import SnubaQueryEventType
from sentry.testutils.cases import APITestCase
from sentry.testutils.silo import region_silo_test
from sentry.workflow_engine.models import DataSourceDetector, Detector
from sentry.workflow_engine.models.data_condition import Condition
from sentry.workflow_engine.types import DetectorPriorityLevel


class ProjectDetectorDetailsBaseTest(APITestCase):
    endpoint = "sentry-api-0-project-detector-details"

    def setUp(self):
        super().setUp()
        self.login_as(user=self.user)
        self.environment = self.create_environment(
            organization_id=self.organization.id, name="production"
        )
        self.data_source = self.create_data_source(organization=self.organization)
        self.detector = self.create_detector(
            project_id=self.project.id, name="Test Detector", type=MetricAlertFire.slug
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
class ProjectDetectorDetailsPostTest(ProjectDetectorDetailsGetTest):
    method = "PUT"

    def setUp(self):
        super().setUp()
        self.valid_data = {
            "name": "Updated Detector",
            "group_type": MetricAlertFire.slug,
            "data_source": [],
            # "data_source": [ # is this supposed to update the query via the query id?
            #     {
            #         "query_type": SnubaQuery.Type.ERROR.value,
            #         "dataset": Dataset.Events.name.lower(),
            #         "query_id": "test query",
            #         "aggregate": "count()",
            #         "time_window": 60,
            #         "environment": self.environment.name,
            #         "event_types": [SnubaQueryEventType.EventType.ERROR.value],
            #     }
            # ],
            "data_conditions": {
                "type": Condition.GREATER,
                "comparison": 100,
                "result": DetectorPriorityLevel.HIGH,
            },
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

        # data_source_detector = DataSourceDetector.objects.get(detector=detector)
        # data_source = DataSource.objects.get(id=data_source_detector.detector.id)
        # assert data_source.query == "test query"

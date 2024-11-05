import unittest
from unittest import mock

from sentry.issues.grouptype import GroupCategory, GroupType
from sentry.testutils.abstract import Abstract
from sentry.testutils.cases import TestCase
from sentry.workflow_engine.models import DataPacket, Detector, DetectorState
from sentry.workflow_engine.processors.detector import (
    DetectorEvaluationResult,
    DetectorHandler,
    DetectorStateData,
    StatefulDetectorHandler,
    get_redis_client,
    process_detectors,
)
from sentry.workflow_engine.types import DetectorPriorityLevel
from tests.sentry.issues.test_grouptype import BaseGroupTypeTest


class TestProcessDetectors(BaseGroupTypeTest):
    def setUp(self):
        super().setUp()

        class NoHandlerGroupType(GroupType):
            type_id = 1
            slug = "no_handler"
            description = "no handler"
            category = GroupCategory.METRIC_ALERT.value

        class MockDetectorHandler(DetectorHandler[dict]):
            def evaluate(self, data_packet: DataPacket[dict]) -> list[DetectorEvaluationResult]:
                return [DetectorEvaluationResult(None, True, DetectorPriorityLevel.HIGH)]

        class HandlerGroupType(GroupType):
            type_id = 2
            slug = "handler"
            description = "handler"
            category = GroupCategory.METRIC_ALERT.value
            detector_handler = MockDetectorHandler

        class MockDetectorStateHandler(DetectorHandler[dict]):
            def evaluate(self, data_packet: DataPacket[dict]) -> list[DetectorEvaluationResult]:
                group_keys = data_packet.packet.get("group_keys", [None])
                return [
                    DetectorEvaluationResult(
                        group_key,
                        True,
                        DetectorPriorityLevel.HIGH,
                    )
                    for group_key in group_keys
                ]

        class HandlerStateGroupType(GroupType):
            type_id = 3
            slug = "handler_with_state"
            description = "handler with state"
            category = GroupCategory.METRIC_ALERT.value
            detector_handler = MockDetectorStateHandler

        self.no_handler_type = NoHandlerGroupType
        self.handler_type = HandlerGroupType
        self.handler_state_type = HandlerStateGroupType

    def build_data_packet(self, **kwargs):
        query_id = "1234"
        return DataPacket[dict](query_id, {"query_id": query_id, "some": "data", **kwargs})

    def test(self):
        detector = self.create_detector(type=self.handler_type.slug)
        data_packet = self.build_data_packet()
        results = process_detectors(data_packet, [detector])
        assert results == [
            (
                detector,
                [DetectorEvaluationResult(None, True, DetectorPriorityLevel.HIGH)],
            )
        ]

    def test_state_results(self):
        detector = self.create_detector(type=self.handler_state_type.slug)
        data_packet = self.build_data_packet()
        results = process_detectors(data_packet, [detector])
        result = DetectorEvaluationResult(
            None,
            True,
            DetectorPriorityLevel.HIGH,
        )
        assert results == [
            (
                detector,
                [result],
            )
        ]

    def test_state_results_multi_group(self):
        detector = self.create_detector(type=self.handler_state_type.slug)
        data_packet = self.build_data_packet(group_keys=["group_1", "group_2"])
        results = process_detectors(data_packet, [detector])
        result_1 = DetectorEvaluationResult(
            "group_1",
            True,
            DetectorPriorityLevel.HIGH,
        )
        result_2 = DetectorEvaluationResult(
            "group_2",
            True,
            DetectorPriorityLevel.HIGH,
        )
        assert results == [
            (
                detector,
                [result_1, result_2],
            )
        ]

    def test_state_results_multi_group_dupe(self):
        detector = self.create_detector(type=self.handler_state_type.slug)
        data_packet = self.build_data_packet(group_keys=["dupe", "dupe"])
        with mock.patch("sentry.workflow_engine.processors.detector.logger") as mock_logger:
            results = process_detectors(data_packet, [detector])
            assert mock_logger.error.call_args[0][0] == "Duplicate detector state group keys found"
        result = DetectorEvaluationResult(
            "dupe",
            True,
            DetectorPriorityLevel.HIGH,
        )
        assert results == [
            (
                detector,
                [result, result],
            )
        ]

    def test_no_issue_type(self):
        detector = self.create_detector(type="invalid slug")
        data_packet = self.build_data_packet()
        with mock.patch("sentry.workflow_engine.models.detector.logger") as mock_logger:
            results = process_detectors(data_packet, [detector])
            assert mock_logger.error.call_args[0][0] == "No registered grouptype for detector"
        assert results == []

    def test_no_handler(self):
        detector = self.create_detector(type=self.no_handler_type.slug)
        data_packet = self.build_data_packet()
        with mock.patch("sentry.workflow_engine.models.detector.logger") as mock_logger:
            results = process_detectors(data_packet, [detector])
            assert (
                mock_logger.error.call_args[0][0]
                == "Registered grouptype for detector has no detector_handler"
            )
        assert results == []


class MockDetectorStateHandler(StatefulDetectorHandler[dict]):
    counter_names = ["test1", "test2"]

    def get_dedupe_value(self, data_packet: DataPacket[dict]) -> int:
        return data_packet.packet.get("dedupe", 0)

    def get_group_key_values(self, data_packet: DataPacket[dict]) -> dict[str, int]:
        return data_packet.packet.get("group_vals", {})


class TestKeyBuilders(unittest.TestCase):
    def build_handler(self, detector: Detector | None = None) -> MockDetectorStateHandler:
        if detector is None:
            detector = Detector(id=123)
        return MockDetectorStateHandler(detector)

    def test(self):
        assert self.build_handler().build_dedupe_value_key("test") == "123:test:dedupe_value"
        assert self.build_handler().build_counter_value_key("test", "name_1") == "123:test:name_1"

    def test_different_dedupe_keys(self):
        handler = self.build_handler()
        handler_2 = self.build_handler(Detector(id=456))
        assert handler.build_dedupe_value_key("test") != handler_2.build_dedupe_value_key("test")
        assert handler.build_dedupe_value_key("test") != handler_2.build_dedupe_value_key("test2")
        assert handler.build_dedupe_value_key("test") == handler.build_dedupe_value_key("test")
        assert handler.build_dedupe_value_key("test") != handler.build_dedupe_value_key("test_2")

    def test_different_counter_value_keys(self):
        handler = self.build_handler()
        handler_2 = self.build_handler(Detector(id=456))
        assert handler.build_counter_value_key(
            "test", "name_1"
        ) != handler_2.build_counter_value_key("test", "name_1")
        assert handler.build_counter_value_key("test", "name_1") == handler.build_counter_value_key(
            "test", "name_1"
        )
        assert handler.build_counter_value_key("test", "name_1") != handler.build_counter_value_key(
            "test2", "name_1"
        )
        assert handler.build_counter_value_key("test", "name_1") != handler.build_counter_value_key(
            "test", "name_2"
        )
        assert handler.build_counter_value_key("test", "name_1") != handler.build_counter_value_key(
            "test2", "name_2"
        )


class StatefulDetectorHandlerTestMixin(TestCase):
    __test__ = Abstract(__module__, __qualname__)

    def build_handler(self, detector: Detector | None = None) -> MockDetectorStateHandler:
        if detector is None:
            detector = self.create_detector(
                workflow_condition_group=self.create_data_condition_group()
            )
            self.create_data_condition(condition_group=detector.workflow_condition_group)
        return MockDetectorStateHandler(detector)

    def assert_updates(self, handler, group_key, dedupe_value, counter_updates, active, priority):
        if dedupe_value is not None:
            assert handler.dedupe_updates.get(group_key) == dedupe_value
        else:
            assert group_key not in handler.dedupe_updates
        if counter_updates is not None:
            assert handler.counter_updates.get(group_key) == counter_updates
        else:
            assert group_key not in handler.counter_updates
        if active is not None or priority is not None:
            assert handler.state_updates.get(group_key) == (active, priority)
        else:
            assert group_key not in handler.state_updates


class TestGetStateData(StatefulDetectorHandlerTestMixin):
    def test_new(self):
        handler = self.build_handler()
        key = "test_key"
        assert handler.get_state_data([key]) == {
            key: DetectorStateData(
                key, False, DetectorPriorityLevel.OK, 0, {"test1": None, "test2": None}
            )
        }

    def test_existing(self):
        handler = self.build_handler()
        key = "test_key"
        state_data = DetectorStateData(
            key, True, DetectorPriorityLevel.OK, 10, {"test1": 5, "test2": 200}
        )
        handler.enqueue_dedupe_update(state_data.group_key, state_data.dedupe_value)
        handler.enqueue_counter_update(state_data.group_key, state_data.counter_updates)
        handler.enqueue_state_update(state_data.group_key, state_data.active, state_data.status)
        handler.commit_state_updates()
        assert handler.get_state_data([key]) == {key: state_data}

    def test_multi(self):
        handler = self.build_handler()
        key_1 = "test_key_1"
        state_data_1 = DetectorStateData(
            key_1, True, DetectorPriorityLevel.OK, 100, {"test1": 50, "test2": 300}
        )
        handler.enqueue_dedupe_update(key_1, state_data_1.dedupe_value)
        handler.enqueue_counter_update(key_1, state_data_1.counter_updates)
        handler.enqueue_state_update(key_1, state_data_1.active, state_data_1.status)

        key_2 = "test_key_2"
        state_data_2 = DetectorStateData(
            key_2, True, DetectorPriorityLevel.OK, 10, {"test1": 55, "test2": 12}
        )
        handler.enqueue_dedupe_update(key_2, state_data_2.dedupe_value)
        handler.enqueue_counter_update(key_2, state_data_2.counter_updates)
        handler.enqueue_state_update(key_2, state_data_2.active, state_data_2.status)

        key_uncommitted = "test_key_uncommitted"
        state_data_uncommitted = DetectorStateData(
            key_uncommitted, False, DetectorPriorityLevel.OK, 0, {"test1": None, "test2": None}
        )
        handler.commit_state_updates()
        assert handler.get_state_data([key_1, key_2, key_uncommitted]) == {
            key_1: state_data_1,
            key_2: state_data_2,
            key_uncommitted: state_data_uncommitted,
        }


class TestCommitStateUpdateData(StatefulDetectorHandlerTestMixin):
    def test(self):
        handler = self.build_handler()
        redis = get_redis_client()
        group_key = None
        assert not DetectorState.objects.filter(
            detector=handler.detector, detector_group_key=group_key
        ).exists()
        dedupe_key = handler.build_dedupe_value_key(group_key)
        counter_key_1 = handler.build_counter_value_key(group_key, "some_counter")
        counter_key_2 = handler.build_counter_value_key(group_key, "another_counter")
        assert not redis.exists(dedupe_key)
        assert not redis.exists(counter_key_1)
        assert not redis.exists(counter_key_2)
        handler.enqueue_dedupe_update(group_key, 100)
        handler.enqueue_counter_update(group_key, {"some_counter": 1, "another_counter": 2})
        handler.enqueue_state_update(group_key, True, DetectorPriorityLevel.OK)
        handler.commit_state_updates()
        assert DetectorState.objects.filter(
            detector=handler.detector,
            detector_group_key=group_key,
            active=True,
            state=DetectorPriorityLevel.OK,
        ).exists()
        assert redis.get(dedupe_key) == "100"
        assert redis.get(counter_key_1) == "1"
        assert redis.get(counter_key_2) == "2"

        handler.enqueue_dedupe_update(group_key, 150)
        handler.enqueue_counter_update(group_key, {"some_counter": None, "another_counter": 20})
        handler.enqueue_state_update(group_key, False, DetectorPriorityLevel.OK)
        handler.commit_state_updates()
        assert DetectorState.objects.filter(
            detector=handler.detector,
            detector_group_key=group_key,
            active=False,
            state=DetectorPriorityLevel.OK,
        ).exists()
        assert redis.get(dedupe_key) == "150"
        assert not redis.exists(counter_key_1)
        assert redis.get(counter_key_2) == "20"


class TestEvaluate(StatefulDetectorHandlerTestMixin):
    def test(self):
        handler = self.build_handler()
        assert handler.evaluate(DataPacket("1", {"dedupe": 1})) == []
        assert handler.evaluate(DataPacket("1", {"dedupe": 2, "group_vals": {"val1": 0}})) == [
            DetectorEvaluationResult(
                group_key="val1",
                is_active=True,
                priority=DetectorPriorityLevel.HIGH,
            )
        ]
        self.assert_updates(handler, "val1", 2, {}, True, DetectorPriorityLevel.HIGH)

    def test_no_condition_group(self):
        detector = self.create_detector()
        handler = MockDetectorStateHandler(detector)
        with mock.patch("sentry.workflow_engine.processors.detector.metrics") as mock_metrics:
            assert (
                handler.evaluate(DataPacket("1", {"dedupe": 2, "group_vals": {"val1": 100}})) == []
            )
            mock_metrics.incr.assert_called_once_with(
                "workflow_engine.detector.skipping_invalid_condition_group"
            )
            self.assert_updates(handler, "val1", 2, None, None, None)

    def test_results_on_change(self):
        handler = self.build_handler()
        result = handler.evaluate(DataPacket("1", {"dedupe": 2, "group_vals": {"val1": 100}}))
        assert result == [
            DetectorEvaluationResult(
                group_key="val1",
                is_active=True,
                priority=DetectorPriorityLevel.HIGH,
            )
        ]
        self.assert_updates(handler, "val1", 2, {}, True, DetectorPriorityLevel.HIGH)
        handler.commit_state_updates()
        # This detector is already active, so no status change occurred. Should be no result
        assert handler.evaluate(DataPacket("1", {"dedupe": 3, "group_vals": {"val1": 200}})) == []

    def test_dedupe(self):
        handler = self.build_handler()
        result = handler.evaluate(DataPacket("1", {"dedupe": 2, "group_vals": {"val1": 0}}))
        assert result == [
            DetectorEvaluationResult(
                group_key="val1",
                is_active=True,
                priority=DetectorPriorityLevel.HIGH,
            )
        ]
        self.assert_updates(handler, "val1", 2, {}, True, DetectorPriorityLevel.HIGH)
        handler.commit_state_updates()
        with mock.patch("sentry.workflow_engine.processors.detector.metrics") as mock_metrics:
            assert handler.evaluate(DataPacket("1", {"dedupe": 2, "group_vals": {"val1": 0}})) == []
            mock_metrics.incr.assert_called_once_with(
                "workflow_engine.detector.skipping_already_processed_update"
            )
        self.assert_updates(handler, "val1", None, None, None, None)


class TestEvaluateGroupKeyValue(StatefulDetectorHandlerTestMixin):
    def test_dedupe(self):
        handler = self.build_handler()
        with mock.patch("sentry.workflow_engine.processors.detector.metrics") as mock_metrics:
            expected_result = DetectorEvaluationResult(
                "group_key",
                True,
                DetectorPriorityLevel.HIGH,
            )
            assert (
                handler.evaluate_group_key_value(
                    expected_result.group_key,
                    1,
                    DetectorStateData(
                        "group_key",
                        False,
                        DetectorPriorityLevel.OK,
                        99,
                        {},
                    ),
                    dedupe_value=100,
                )
                == expected_result
            )
            assert not mock_metrics.incr.called
            assert (
                handler.evaluate_group_key_value(
                    expected_result.group_key,
                    1,
                    DetectorStateData(
                        "group_key",
                        False,
                        DetectorPriorityLevel.OK,
                        100,
                        {},
                    ),
                    dedupe_value=100,
                )
                is None
            )
            mock_metrics.incr.assert_called_once_with(
                "workflow_engine.detector.skipping_already_processed_update"
            )

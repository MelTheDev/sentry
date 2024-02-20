from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from snuba_sdk import And, Condition, Op, Or

from sentry import options
from sentry.search.events.builder import QueryBuilder, SpansIndexedQueryBuilder
from sentry.search.events.types import QueryBuilderConfig, SnubaParams
from sentry.snuba.dataset import Dataset
from sentry.snuba.metrics.naming_layer.mri import SpanMRI, TransactionMRI
from sentry.snuba.referrer import Referrer


class SamplesListExecutor(ABC):
    def __init__(
        self,
        mri: str,
        params: dict[str, Any],
        snuba_params: SnubaParams,
        fields: list[str],
        query: str | None,
        rollup: int,
        referrer: Referrer,
    ):
        self.mri = mri
        self.params = params
        self.snuba_params = snuba_params
        self.fields = fields
        self.query = query
        self.rollup = rollup
        self.referrer = referrer

    @classmethod
    @abstractmethod
    def supports(cls, metric_mri: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def execute(self, offset, limit):
        raise NotImplementedError

    def get_spans_by_key(self, span_ids: list[tuple[str, str, str]]):
        if not span_ids:
            return {"data": []}

        builder = SpansIndexedQueryBuilder(
            Dataset.SpansIndexed,
            self.params,
            snuba_params=self.snuba_params,
            selected_columns=self.fields,
            limit=len(span_ids),
            offset=0,
        )

        # Using `IN` sometimes does not use the bloomfilter index
        # on the table. So we're explicitly writing the condition
        # using `OR`s.
        #
        # May not be necessary because it's also filtering on the
        # `span.group` as well which allows Clickhouse to filter
        # via the primary key but this is a precaution.
        conditions = [
            And(
                [
                    Condition(builder.column("span.group"), Op.EQ, group),
                    Condition(
                        builder.column("timestamp"), Op.EQ, datetime.fromisoformat(timestamp)
                    ),
                    Condition(builder.column("id"), Op.EQ, span_id),
                ]
            )
            for (group, timestamp, span_id) in span_ids
        ]

        if len(conditions) == 1:
            span_condition = conditions[0]
        else:
            span_condition = Or(conditions)

        builder.add_conditions([span_condition])

        query_results = builder.run_query(self.referrer.value)
        return builder.process_results(query_results)


class SegmentsSamplesListExecutor(SamplesListExecutor):
    @classmethod
    def mri_to_column(cls, mri) -> str | None:
        if mri == TransactionMRI.DURATION.value:
            return "duration"
        return None

    @classmethod
    def supports(cls, mri: str) -> bool:
        return cls.mri_to_column(mri) is not None

    def execute(self, offset, limit):
        span_keys = self.get_span_keys(offset, limit)
        return self.get_spans_by_key(span_keys)

    def get_span_keys(self, offset: int, limit: int) -> list[tuple[str, str, str]]:
        rounded_timestamp = f"rounded_timestamp({self.rollup})"

        builder = QueryBuilder(
            Dataset.Transactions,
            self.params,
            snuba_params=self.snuba_params,
            query=self.query,
            selected_columns=[rounded_timestamp, "example()"],
            limit=limit,
            offset=offset,
            sample_rate=options.get("metrics.sample-list.sample-rate"),
            config=QueryBuilderConfig(functions_acl=["rounded_timestamp", "example"]),
        )

        query_results = builder.run_query(self.referrer.value)
        result = builder.process_results(query_results)

        return [
            (
                "00",  # all segments have a group of `00` currently
                row["example"][0],  # timestamp
                row["example"][1],  # span_id
            )
            for row in result["data"]
        ]


class SpansSamplesListExecutor(SamplesListExecutor):
    MRI_MAPPING = {
        SpanMRI.DURATION.value: "span.duration",
        SpanMRI.SELF_TIME.value: "span.self_time",
    }

    @classmethod
    def mri_to_column(cls, mri) -> str | None:
        return cls.MRI_MAPPING.get(mri)

    @classmethod
    def supports(cls, mri: str) -> bool:
        return cls.mri_to_column(mri) is not None

    def execute(self, offset, limit):
        span_keys = self.get_span_keys(offset, limit)
        return self.get_spans_by_key(span_keys)

    def get_span_keys(self, offset: int, limit: int) -> list[tuple[str, str, str]]:
        rounded_timestamp = f"rounded_timestamp({self.rollup})"

        builder = SpansIndexedQueryBuilder(
            Dataset.SpansIndexed,
            self.params,
            snuba_params=self.snuba_params,
            query=self.query,
            selected_columns=[rounded_timestamp, "example()"],
            limit=limit,
            offset=offset,
            sample_rate=options.get("metrics.sample-list.sample-rate"),
            config=QueryBuilderConfig(functions_acl=["rounded_timestamp", "example"]),
        )

        builder.add_conditions(
            [
                # The `00` group is used for spans not used within the
                # new starfish experience. It's effectively the group
                # for other. It is a massive group, so we've chosen
                # to exclude it here.
                #
                # In the future, we will want to look into exposing them
                Condition(builder.column("span.group"), Op.NEQ, "00")
            ]
        )

        query_results = builder.run_query(self.referrer.value)
        result = builder.process_results(query_results)

        return [
            (
                row["example"][0],  # group
                row["example"][1],  # timestamp
                row["example"][2],  # span_id
            )
            for row in result["data"]
        ]


SAMPLE_LIST_EXECUTORS = [
    SpansSamplesListExecutor,
    SegmentsSamplesListExecutor,
]


def get_sample_list_executor_cls(mri) -> type[SamplesListExecutor] | None:
    for executor_cls in SAMPLE_LIST_EXECUTORS:
        if executor_cls.supports(mri):
            return executor_cls
    return None

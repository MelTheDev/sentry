from __future__ import annotations

import string
from collections.abc import Iterator
from typing import Any, ClassVar, TypeVar

from django.utils.encoding import force_str

from sentry.interfaces.base import Interface
from sentry.utils.json import prune_empty_keys
from sentry.utils.safe import get_path

__all__ = ("Contexts",)

ContextTypeT = TypeVar("ContextTypeT", bound="ContextType")

context_types: dict[str, type[ContextType]] = {}


class _IndexFormatter(string.Formatter):
    def format_field(self, value: object, format_spec: str) -> str:
        if not format_spec and isinstance(value, bool):
            return value and "yes" or "no"
        return string.Formatter.format_field(self, value, format_spec)


def format_index_expr(format_string: str, data: dict[str, object]) -> str:
    return str(_IndexFormatter().vformat(str(format_string), (), data).strip())


def contexttype(cls: type[ContextTypeT]) -> type[ContextTypeT]:
    context_types[cls.type] = cls
    return cls


# NOTE: Are you adding a new context? Make sure to also update the
# documentation in the sentry develop docs [0]!
#
# [0]: https://develop.sentry.dev/sdk/event-payloads/contexts


class ContextType:
    context_to_tag_mapping: ClassVar[dict[str, str]] = {}
    """
    This indicates which fields should be promoted into tags during event
    normalization. (See EventManager)

    The key for each entry is used as the name of the tag suffixed by the
    "alias" of the context (this is the key of the context in the contexts
    object, it is NOT the `type` of the context, though they are often the
    same).

    The value is a format string spec that uses python string.Formatter to
    interpolate any value from the context object.

    There is one special case:

     - When the key of the mapping is an empty string the tag name will simply be
       the alias.

    For example if you have a context named "myContext" with the data:

    ```json
    "myContext": {
        "some_value": "hello world",
        "subkey": "whatever",
        "type": "myContext"
    }
    ```

    and you have a context_to_tag_mapping that looks like

    ```python
    context_to_tag_mapping = {"": "{some_value}", "subkey": "{subkey}"}
    ```

    Then normalization will result in two tags being promoted:

     - myContext: "hello world"
     - myContext.subkey: "whatever"
    """

    type: str
    """This should match the `type` key in context object"""

    def __init__(self, alias: str, data: dict[str, object]) -> None:
        self.alias = alias
        ctx_data = {}
        for key, value in data.items():
            # we use a simple check here, rather than ' in set()' to avoid
            # issues with maps/lists.

            # Even if the value is an empty string,
            # we still want to display the info the UI
            if value is not None:
                ctx_data[force_str(key)] = value
            # Numbers exceeding 15 place values will be converted to strings to avoid rendering issues
            if isinstance(value, (int, float, list, dict)):
                ctx_data[force_str(key)] = self.change_type(value)
        self.data = ctx_data

    def to_json(self) -> dict[str, object]:
        rv = dict(self.data)
        rv["type"] = self.type
        return prune_empty_keys(rv)

    @classmethod
    def values_for_data(cls, data: dict[str, Any]) -> list[dict[str, object]]:
        rv = []
        for context in (data.get("contexts") or {}).values():
            if context and context.get("type") == cls.type:
                rv.append(context)
        return rv

    @classmethod
    def primary_value_for_data(cls: Any, data: dict[str, object]) -> dict[str, object] | None:
        val = get_path(data, "contexts", cls.type)
        if val and val.get("type") == cls.type:
            return val

        rv = cls.values_for_data(data)
        if len(rv) == 1:
            return rv[0]
        return None

    def iter_tags(self) -> Iterator[tuple[str, str]]:
        if self.context_to_tag_mapping:
            for field, f_string in self.context_to_tag_mapping.items():
                try:
                    value = format_index_expr(f_string, self.data)
                except KeyError:
                    continue
                if value:
                    if not field:
                        yield (self.alias, value)
                    else:
                        yield (f"{self.alias}.{field}", value)

    def change_type(self, value: int | float | list[Any] | dict[str, Any]) -> object:
        if isinstance(value, (float, int)) and len(str_value := force_str(value)) > 15:
            return str_value
        if isinstance(value, list):
            return [self.change_type(el) for el in value]
        elif isinstance(value, dict):
            return {key: self.change_type(el) for key, el in value.items()}
        else:
            return value


# TODO(dcramer): contexts need to document/describe expected (optional) fields
@contexttype
class DefaultContextType(ContextType):
    type = "default"


@contexttype
class AppContextType(ContextType):
    type = "app"
    context_to_tag_mapping = {"device": "{device_app_hash}"}


@contexttype
class DeviceContextType(ContextType):
    type = "device"
    context_to_tag_mapping = {"": "{model}", "family": "{family}"}
    # model_id, arch


@contexttype
class RuntimeContextType(ContextType):
    type = "runtime"
    context_to_tag_mapping = {"": "{name} {version}", "name": "{name}"}


@contexttype
class BrowserContextType(ContextType):
    type = "browser"
    context_to_tag_mapping = {"": "{name} {version}", "name": "{name}"}
    # viewport


@contexttype
class OsContextType(ContextType):
    type = "os"
    context_to_tag_mapping = {"": "{name} {version}", "name": "{name}", "rooted": "{rooted}"}
    # build, rooted


@contexttype
class GpuContextType(ContextType):
    type = "gpu"
    context_to_tag_mapping = {"name": "{name}", "vendor": "{vendor_name}"}


@contexttype
class MonitorContextType(ContextType):
    type = "monitor"
    context_to_tag_mapping = {"id": "{id}", "slug": "{slug}"}


@contexttype
class TraceContextType(ContextType):
    type = "trace"
    context_to_tag_mapping = {}


@contexttype
class OtelContextType(ContextType):
    type = "otel"
    context_to_tag_mapping = {}


class Contexts(Interface):
    """
    This interface stores context specific information.
    """

    display_score = 1100
    score = 800

    @classmethod
    def to_python(cls: Any, data: dict[str, Any], **kwargs: Any) -> dict[str, Any] | None:
        rv = {}

        # Note the alias is the key of the context entry
        for alias, value in data.items():
            # XXX(markus): The `None`-case should be handled in the UI and
            # other consumers of this interface
            if value is not None:
                rv[alias] = cls.normalize_context(alias, value)

        return super().to_python(rv, **kwargs)

    @classmethod
    def normalize_context(cls: Any, alias: str, data: dict[str, Any]) -> ContextType:
        ctx_type = data.get("type", alias)
        ctx_cls = context_types.get(ctx_type, DefaultContextType)
        return ctx_cls(alias, data)

    def iter_contexts(self) -> list[ContextType]:
        return list(self._data.values())

    def to_json(self) -> dict[str, dict[str, object]]:
        rv = {}
        for alias, inst in self._data.items():
            rv[alias] = inst.to_json()
        return rv

    def iter_tags(self) -> Iterator[tuple[str, str]]:
        for inst in self.iter_contexts():
            yield from inst.iter_tags()

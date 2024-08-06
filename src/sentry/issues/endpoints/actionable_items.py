from typing import TypedDict

from django.db.models import F
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from sentry import eventstore
from sentry.api.api_owners import ApiOwner
from sentry.api.api_publish_status import ApiPublishStatus
from sentry.api.base import region_silo_endpoint
from sentry.api.bases.project import ProjectEndpoint
from sentry.api.helpers.actionable_items_helper import (
    ActionPriority,
    deprecated_event_errors,
    errors_to_hide,
    priority_ranking,
)
from sentry.integrations.base import IntegrationFeatures
from sentry.integrations.services.integration import integration_service
from sentry.models.actionableitemsissues import ActionableItemsIssues
from sentry.models.eventerror import EventError
from sentry.models.project import Project
from sentry.utils.platform_categories import REPLAY_PLATFORMS


class ActionableItemResponse(TypedDict):
    type: str
    message: str
    data: dict | None


class SourceMapProcessingResponse(TypedDict):
    errors: list[ActionableItemResponse]


@region_silo_endpoint
class ActionableItemsEndpoint(ProjectEndpoint):
    """
    This endpoint is used to retrieve actionable items that a user can perform on an event. It is a private endpoint
    that is only used by the Sentry UI. The Source Map Debugging endpoint will remain public as it will only ever
    return information about the source map debugging process while this endpoint will grow. Actionable items are
    errors or messages we show to users about problems with their event which we will show the user how to fix.
    """

    publish_status = {
        "GET": ApiPublishStatus.PRIVATE,
    }
    owner = ApiOwner.ISSUES

    def get(self, request: Request, project: Project, event_id: str) -> Response:
        # Retrieve information about actionable items (source maps, event errors, etc.) for a given event.
        event = eventstore.backend.get_event_by_id(project.id, event_id)
        if event is None:
            raise NotFound(detail="Event not found")

        actions = []
        event_errors = event.data.get("errors", [])

        # Add event errors to actionable items
        for event_error in event_errors:
            if (
                event_error["type"] in errors_to_hide
                or event_error["type"] in deprecated_event_errors
            ):
                continue
            response = EventError(event_error).get_api_context()

            actions.append(response)

        # Check if replays are set up
        if project.platform:
            org_has_sent_replays = (
                Project.objects.filter(organization=project.organization)
                .filter(flags=F("flags").bitor(Project.flags.has_replays))
                .exists()
            )
            if project.platform in REPLAY_PLATFORMS and not org_has_sent_replays:
                actions.append(
                    {
                        "type": ActionableItemsIssues.REPLAY_NOT_SETUP,
                        "message": "Replays are not set up for this organization",
                        "data": {},
                    }
                )

        # Check for Git integrations

        integrations = integration_service.get_integrations(organization_id=project.organization_id)
        # TODO(meredith): should use get_provider.has_feature() instead once this is
        # no longer feature gated and is added as an IntegrationFeature
        has_git_integrations = (
            len(filter(lambda i: i.has_feature(IntegrationFeatures.STACKTRACE_LINK)), integrations)
            > 0
        )

        if not has_git_integrations:
            actions.append(
                {
                    "type": ActionableItemsIssues.MISSING_GIT_INTEGRATION,
                    "message": "No Git integrations are set up for this organization",
                    "data": {},
                }
            )

        priority_get = lambda x: priority_ranking.get(x["type"], ActionPriority.UNKNOWN)
        sorted_errors = sorted(actions, key=priority_get)

        return Response({"errors": sorted_errors})

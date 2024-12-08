from rest_framework.request import Request
from rest_framework.response import Response

from sentry import deletions
from sentry.api.api_publish_status import ApiPublishStatus
from sentry.api.base import region_silo_endpoint
from sentry.sentry_apps.api.bases.sentryapps import (
    SentryAppInstallationExternalIssueBaseEndpoint as ExternalIssueBaseEndpoint,
)
from sentry.sentry_apps.models.platformexternalissue import PlatformExternalIssue


@region_silo_endpoint
class SentryAppInstallationExternalIssueDetailsEndpoint(ExternalIssueBaseEndpoint):
    publish_status = {
        "DELETE": ApiPublishStatus.UNKNOWN,
    }

    def delete(self, request: Request, installation, external_issue_id) -> Response:
        try:
            platform_external_issue = PlatformExternalIssue.objects.get(
                id=external_issue_id,
                project__organization_id=installation.organization_id,
                service_type=installation.sentry_app.slug,
            )
        except PlatformExternalIssue.DoesNotExist:
            return Response({"error": "Could not find requested external issue"}, status=404)

        deletions.exec_sync(platform_external_issue)

        return Response(status=204)

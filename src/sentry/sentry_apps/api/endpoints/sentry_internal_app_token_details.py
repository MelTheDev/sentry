from django.db import router, transaction
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from sentry import analytics, deletions
from sentry.api.api_owners import ApiOwner
from sentry.api.api_publish_status import ApiPublishStatus
from sentry.api.base import control_silo_endpoint
from sentry.api.exceptions import ResourceDoesNotExist
from sentry.coreapi import APIUnauthorized
from sentry.models.apitoken import ApiToken
from sentry.sentry_apps.api.bases.sentryapps import (
    SentryAppBaseEndpoint,
    SentryInternalAppTokenPermission,
)
from sentry.sentry_apps.api.endpoints.sentry_app_details import PARTNERSHIP_RESTRICTED_ERROR_MESSAGE
from sentry.sentry_apps.models.sentry_app_installation_token import SentryAppInstallationToken
from sentry.sentry_apps.utils.errors import (
    SentryAppIntegratorError,
    catch_and_handle_sentry_app_errors,
)


@control_silo_endpoint
class SentryInternalAppTokenDetailsEndpoint(SentryAppBaseEndpoint):
    owner = ApiOwner.INTEGRATIONS
    publish_status = {
        "DELETE": ApiPublishStatus.PRIVATE,
    }
    permission_classes = (SentryInternalAppTokenPermission,)

    def convert_args(self, request: Request, sentry_app_id_or_slug, api_token_id, *args, **kwargs):
        # get the sentry_app from the SentryAppBaseEndpoint class
        (args, kwargs) = super().convert_args(request, sentry_app_id_or_slug, *args, **kwargs)

        try:
            kwargs["api_token"] = ApiToken.objects.get(id=api_token_id)
        except (ApiToken.DoesNotExist, ValueError):
            raise SentryAppIntegratorError(
                ResourceDoesNotExist("Couldn't find the given api token"), status_code=404
            )

        return (args, kwargs)

    @catch_and_handle_sentry_app_errors
    def delete(self, request: Request, sentry_app, api_token) -> Response:
        # Validate the token is associated with the application
        if api_token.application_id != sentry_app.application_id:
            raise SentryAppIntegratorError(
                APIUnauthorized("Given token is not owned by this sentry app"), status_code=403
            )

        if not sentry_app.is_internal:
            return Response(
                "This route is limited to internal integrations only",
                status=status.HTTP_403_FORBIDDEN,
            )

        if sentry_app.metadata.get("partnership_restricted", False):
            return Response(
                {"detail": PARTNERSHIP_RESTRICTED_ERROR_MESSAGE},
                status=403,
            )

        with transaction.atomic(using=router.db_for_write(SentryAppInstallationToken)):
            try:
                install_token = SentryAppInstallationToken.objects.get(api_token=api_token)
                sentry_app_installation = install_token.sentry_app_installation
            except SentryAppInstallationToken.DoesNotExist:
                raise SentryAppIntegratorError(
                    ResourceDoesNotExist("Could not find given token"), status_code=404
                )

            deletions.exec_sync(install_token)

        analytics.record(
            "sentry_app_installation_token.deleted",
            user_id=request.user.id,
            organization_id=sentry_app_installation.organization_id,
            sentry_app_installation_id=sentry_app_installation.id,
            sentry_app=sentry_app.slug,
        )

        return Response(status=204)

from typing import Any

import sentry_sdk
from rest_framework.request import Request
from rest_framework.response import Response

from sentry.api.base import control_silo_endpoint
from sentry.constants import ObjectStatus
from sentry.integrations.models.integration import Integration
from sentry.integrations.services.integration.model import RpcIntegration
from sentry.integrations.utils.atlassian_connect import get_integration_from_jwt
from sentry.integrations.utils.scope import bind_org_context_from_integration

from .base import JiraWebhookBase


@control_silo_endpoint
class JiraSentryUninstalledWebhook(JiraWebhookBase):
    """
    Webhook hit by Jira whenever someone uninstalls the Sentry integration from their Jira instance.
    """

    def authenticate(self, request: Request, **kwargs) -> Any:
        token = self.get_token(request)
        rpc_integration = get_integration_from_jwt(
            token=token,
            path=request.path,
            provider=self.provider,
            query_params=request.GET,
            method="POST",
        )
        return rpc_integration

    def unpack_payload(self, request: Request, **kwargs) -> Any:
        # unused
        return None

    def post(self, request: Request, *args, **kwargs) -> Response:
        rpc_integration = self.authenticate(request)
        assert isinstance(rpc_integration, RpcIntegration)

        integration = Integration.objects.get(id=rpc_integration.id)
        bind_org_context_from_integration(integration.id, {"webhook": "uninstalled"})
        sentry_sdk.set_tag("integration_id", integration.id)

        integration.update(status=ObjectStatus.DISABLED)

        return self.respond()

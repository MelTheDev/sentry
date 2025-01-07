"""
    This list is tracking old api endpoints that we couldn't find owners for.
    The goal is to eventually find owners for all and shrink this list.
    DO NOT ADD ANY NEW APIS
"""

API_OWNERSHIP_ALLOWLIST_DONT_MODIFY = [
    "/api/0/organizations/{organization_id_or_slug}/invite-requests/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/stats/",
    "/api/0/sentry-app-installations/{uuid}/external-issues/{external_issue_id}/",
    "/api/0/organizations/{organization_id_or_slug}/releases/{version}/deploys/",
    "/api/0/accept-transfer/",
    "/api/0/organizations/{organization_id_or_slug}/releases/stats/",
    "/api/0/users/{user_id}/subscriptions/",
    "/api/0/organizations/{organization_id_or_slug}/",
    "/api/0/users/{user_id}/identities/{identity_id}/",
    "/api/0/userroles/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/releases/",
    "/api/0/organizations/{organization_id_or_slug}/invite-requests/{member_id}/",
    "/api/0/organizations/",
    "/api/0/organizations/{organization_id_or_slug}/pinned-searches/",
    "/api/0/organizations/{organization_id_or_slug}/data-export/",
    "/api/0/organizations/{organization_id_or_slug}/releases/{version}/meta/",
    "/api/0/users/{user_id}/organizations/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/releases/{version}/",
    "/api/0/users/{user_id}/emails/confirm/",
    "/api/0/users/{user_id}/identities/",
    "/api/0/",
    "/api/0/organizations/{organization_id_or_slug}/avatar/",
    "/api/0/projects/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/releases/completion/",
    "/api/0/sentry-apps/{sentry_app_id_or_slug}/stats/",
    "/api/0/users/{user_id}/emails/",
    "/api/0/organizations/{organization_id_or_slug}/users/{user_id}/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/keys/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/filters/",
    "/api/0/organizations/{organization_id_or_slug}/join-request/",
    "/api/0/organizations/{organization_id_or_slug}/teams/",
    "/api/0/prompts-activity/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/repo-path-parsing/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/transfer/",
    "/api/0/organizations/{organization_id_or_slug}/users/",
    "/api/0/users/{user_id}/user-identities/{category}/{identity_id}/",
    "/api/0/organizations/{organization_id_or_slug}/projects-count/",
    "/api/0/organizations/{organization_id_or_slug}/releases/{version}/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/releases/{version}/repositories/",
    "/api/0/organizations/{organization_id_or_slug}/releases/{version}/commits/",
    "/api/0/users/{user_id}/ips/",
    "/api/0/api-applications/{app_id}/",
    "/api/0/users/{user_id}/roles/{role_name}/",
    "/api/0/organizations/{organization_id_or_slug}/releases/",
    "/api/0/organizations/{organization_id_or_slug}/releases/{version}/files/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/",
    "/api/0/organizations/{organization_id_or_slug}/minimal-projects/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/releases/{version}/commits/",
    "/api/0/users/{user_id}/roles/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/keys/{key_id}/",
    "/api/0/organizations/{organization_id_or_slug}/recent-searches/",
    "/api/0/organizations/{organization_id_or_slug}/projects/",
    "/api/0/accept-invite/{member_id}/{token}/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/environments/{environment}/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/releases/token/",
    "/api/0/organizations/{organization_id_or_slug}/searches/{search_id}/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/user-stats/",
    "/api/0/teams/{organization_id_or_slug}/{team_id_or_slug}/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/users/",
    "/api/0/api-applications/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/tags/",
    "/api/0/broadcasts/{broadcast_id}/",
    "/api/0/organizations/{organization_id_or_slug}/prompts-activity/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/releases/{version}/files/{file_id}/",
    "/api/0/userroles/{role_name}/",
    "/api/0/organizations/{organization_id_or_slug}/environments/",
    "/api/0/users/{user_id}/avatar/",
    "/api/0/organizations/{organization_id_or_slug}/slugs/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/tags/{key}/",
    "/api/0/organizations/{organization_id_or_slug}/broadcasts/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/filters/{filter_id}/",
    "/api/0/accept-invite/{organization_id_or_slug}/{member_id}/{token}/",
    "/api/0/users/",
    "/api/0/broadcasts/",
    "/api/0/organizations/{organization_id_or_slug}/releases/{version}/files/{file_id}/",
    "/api/0/teams/{organization_id_or_slug}/{team_id_or_slug}/release-count/",
    "/api/0/organizations/{organization_id_or_slug}/releases/{version}/assemble/",
    "/api/0/users/{user_id}/user-identities/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/releases/{version}/files/",
    "/api/0/organizations/{organization_id_or_slug}/request-project-creation/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/environments/",
    "/api/0/users/{user_id}/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/releases/{version}/stats/",
    "/_warmup/",
    "/api/0/projects/{organization_id_or_slug}/{project_id_or_slug}/tags/{key}/values/",
]

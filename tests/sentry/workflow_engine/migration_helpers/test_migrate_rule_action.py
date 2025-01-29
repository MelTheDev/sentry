import dataclasses
from unittest.mock import patch

from sentry.eventstore.models import GroupEvent
from sentry.testutils.cases import TestCase
from sentry.workflow_engine.migration_helpers.rule_action import (
    build_notification_actions_from_rule_data_actions,
)
from sentry.workflow_engine.models.action import Action
from sentry.workflow_engine.typings.notification_action import (
    EXCLUDED_ACTION_DATA_KEYS,
    JiraDataBlob,
    issue_alert_action_translator_registry,
)


class TestNotificationActionMigrationUtils(TestCase):
    def setUp(self):
        self.group = self.create_group(project=self.project)
        self.group_event = GroupEvent.from_event(self.event, self.group)

    def assert_action_data_blob(
        self,
        action: Action,
        compare_dict: dict,
        integration_id_key: str | None = None,
        target_identifier_key: str | None = None,
        target_display_key: str | None = None,
    ):
        """
        Asserts that the action data is equivalent to the compare_dict.
        Uses the translator to determine which keys should be excluded from the data blob.
        """
        translator_class = issue_alert_action_translator_registry.get(compare_dict["id"])
        translator = translator_class(compare_dict)

        # Get the keys we need to ignore
        exclude_keys = [*EXCLUDED_ACTION_DATA_KEYS]
        if integration_id_key:
            exclude_keys.append(integration_id_key)
        if target_identifier_key:
            exclude_keys.append(target_identifier_key)
        if target_display_key:
            exclude_keys.append(target_display_key)

        # If we have a blob type, verify the data matches the blob structure
        if translator.blob_type:
            # Special handling for JiraDataBlob which has additional_fields
            if translator.blob_type == JiraDataBlob:
                # Get standard fields from JiraDataBlob, excluding additional_fields
                standard_fields = {
                    f.name
                    for f in dataclasses.fields(JiraDataBlob)
                    if f.name != "additional_fields"
                }

                # Check standard fields
                for field in standard_fields:
                    assert action.data.get(field, "") == compare_dict.get(field, "")

                # Check that additional_fields contains all other non-excluded fields
                additional_fields = action.data.get("additional_fields", {})
                for key, value in compare_dict.items():
                    if (
                        key not in exclude_keys
                        and key not in standard_fields
                        and key != "id"
                        and value  # Only check non-empty values
                    ):
                        assert additional_fields.get(key) == value

                # Ensure no unexpected fields
                expected_keys = standard_fields | {"additional_fields"}
                assert set(action.data.keys()) == expected_keys
            else:
                # Original logic for other blob types
                for field in translator.blob_type.__dataclass_fields__:
                    mapping = translator.field_mappings.get(field)
                    if mapping:
                        # For mapped fields, check against the source field with default value
                        source_value = compare_dict.get(mapping.source_field, mapping.default_value)
                        assert action.data.get(field) == source_value
                    else:
                        # For unmapped fields, check directly with empty string default
                        assert action.data.get(field) == compare_dict.get(field, "")
                # Ensure no extra fields
                assert set(action.data.keys()) == {
                    f.name for f in translator.blob_type.__dataclass_fields__.values()
                }
        else:
            # Assert the rest of the data is the same
            for key in compare_dict:
                if key not in exclude_keys:
                    assert compare_dict[key] == action.data[key]

            # Assert the action data blob doesn't contain more than the keys in the compare_dict
            for key in action.data:
                assert key not in exclude_keys

    def assert_action_attributes(
        self,
        action: Action,
        compare_dict: dict[str, str],
        integration_id_key: str | None = None,
        target_identifier_key: str | None = None,
        target_display_key: str | None = None,
    ):
        """
        Asserts that the action attributes are equivalent to the compare_dict using the translator.
        """
        translator_class = issue_alert_action_translator_registry.get(compare_dict["id"])
        translator = translator_class(compare_dict)

        # Assert action type matches the translator
        assert action.type == translator.action_type

        # Assert integration_id matches if specified
        if integration_id_key:
            assert action.integration_id == compare_dict.get(integration_id_key)

        # Assert target_identifier matches if specified
        if target_identifier_key:
            assert action.target_identifier == compare_dict.get(target_identifier_key)

        # Assert target_display matches if specified
        if target_display_key:
            assert action.target_display == compare_dict.get(target_display_key)

        # Assert target_type matches
        assert action.target_type == translator.target_type

    def assert_actions_migrated_correctly(
        self,
        actions: list[Action],
        rule_data_actions: list[dict],
        integration_id_key: str | None = None,
        target_identifier_key: str | None = None,
        target_display_key: str | None = None,
    ):
        """
        Asserts that the actions are equivalent to the Rule.
        """

        for action, rule_data in zip(actions, rule_data_actions):
            assert isinstance(action, Action)
            self.assert_action_attributes(
                action, rule_data, integration_id_key, target_identifier_key, target_display_key
            )
            self.assert_action_data_blob(
                action, rule_data, integration_id_key, target_identifier_key, target_display_key
            )

    @patch("sentry.workflow_engine.migration_helpers.rule_action.logger.error")
    def test_missing_id_in_action_data(self, mock_logger):
        action_data = [
            {
                "workspace": "1",
                "channel": "#bufo-bot",
                "notes": "@bufo",
                "tags": "level,environment,os",
                "uuid": "b1234567-89ab-cdef-0123-456789abcdef",
                "channel_id": "C01234567890",
            },
        ]

        actions = build_notification_actions_from_rule_data_actions(action_data)
        assert len(actions) == 0

        # Assert the logger was called with the correct arguments
        mock_logger.assert_called_with(
            "No registry ID found for action",
            extra={"action_uuid": "b1234567-89ab-cdef-0123-456789abcdef"},
        )

    @patch("sentry.workflow_engine.migration_helpers.rule_action.logger.exception")
    def test_unregistered_action_translator(self, mock_logger):
        action_data = [
            {
                "workspace": "1",
                "id": "sentry.integrations.slack.notify_action.FakeAction",
                "uuid": "b1234567-89ab-cdef-0123-456789abcdef",
            },
        ]

        actions = build_notification_actions_from_rule_data_actions(action_data)
        assert len(actions) == 0

        # Assert the logger was called with the correct arguments
        mock_logger.assert_called_with(
            "Action translator not found for action",
            extra={
                "registry_id": "sentry.integrations.slack.notify_action.FakeAction",
                "action_uuid": "b1234567-89ab-cdef-0123-456789abcdef",
            },
        )

    def test_slack_action_migration_simple(self):
        action_data = [
            {
                "workspace": "1",
                "id": "sentry.integrations.slack.notify_action.SlackNotifyServiceAction",
                "channel": "#bufo-bot",
                "notes": "@bufo",
                "tags": "level,environment,os",
                "uuid": "b1234567-89ab-cdef-0123-456789abcdef",
                "channel_id": "C01234567890",
            },
            {
                "workspace": "2",
                "id": "sentry.integrations.slack.notify_action.SlackNotifyServiceAction",
                "channel": "#bufo-bot-is-cool",
                "tags": "#ALERT-BUFO",
                "channel_id": "C01234567890",
                "uuid": "f1234567-89ab-cdef-0123-456789abcdef",
            },
            {
                "workspace": "3",
                "id": "sentry.integrations.slack.notify_action.SlackNotifyServiceAction",
                "channel": "sentry-bufo-bot",
                "channel_id": "C1234567890",
                "tags": "",
                "uuid": "g1234567-89ab-cdef-0123-456789abcdef",
            },
            {
                "workspace": "4",
                "id": "sentry.integrations.slack.notify_action.SlackNotifyServiceAction",
                "channel": "#proj-bufo-bot",
                "notes": "@bufo-are-cool",
                "channel_id": "C01234567890",
                "tags": "",
                "uuid": "h1234567-89ab-cdef-0123-456789abcdef",
            },
            {
                "workspace": "5",
                "id": "sentry.integrations.slack.notify_action.SlackNotifyServiceAction",
                "channel": "sentry-bufo-bot",
                "notes": "@bufo-are-cool",
                "channel_id": "C01234567890",
                "uuid": "i1234567-89ab-cdef-0123-456789abcdef",
            },
        ]

        actions = build_notification_actions_from_rule_data_actions(action_data)
        assert len(actions) == len(action_data)

        self.assert_actions_migrated_correctly(
            actions, action_data, "workspace", "channel_id", "channel"
        )

    @patch("sentry.workflow_engine.migration_helpers.rule_action.logger.error")
    def test_slack_action_migration_malformed(self, mock_logger):
        action_data = [
            # Missing required fields
            {
                "workspace": "1",
                "uuid": "b1234567-89ab-cdef-0123-456789abcdef",
                "id": "sentry.integrations.slack.notify_action.SlackNotifyServiceAction",
            },
            {
                "workspace": "1",
                "id": "sentry.integrations.slack.notify_action.SlackNotifyServiceAction",
                "channel": "#bufo-bot",
                "notes": "@bufo",
                "tags": "level,environment,os",
                "uuid": "b1234567-89ab-cdef-0123-456789abcdef",
                "channel_id": "C01234567890",
            },
            {
                "workspace": "2",
                "id": "sentry.integrations.slack.notify_action.SlackNotifyServiceAction",
                "channel": "#bufo-bot-is-cool",
                "tags": "#ALERT-BUFO",
                "channel_id": "C01234567890",
                "uuid": "f1234567-89ab-cdef-0123-456789abcdef",
            },
        ]

        actions = build_notification_actions_from_rule_data_actions(action_data)
        # Only 2 actions should be created, the first one is malformed
        assert len(actions) == 2

        self.assert_actions_migrated_correctly(
            actions, action_data[1:], "workspace", "channel_id", "channel"
        )

        # Assert the logger was called with the correct arguments
        mock_logger.assert_called_with(
            "Action blob is malformed: missing required fields",
            extra={
                "registry_id": "sentry.integrations.slack.notify_action.SlackNotifyServiceAction",
                "action_uuid": "b1234567-89ab-cdef-0123-456789abcdef",
                "missing_fields": ["channel_id", "channel"],
            },
        )

        self.assert_actions_migrated_correctly(actions, action_data[1:])

    def test_discord_action_migration(self):
        action_data = [
            {
                "server": "1",
                "id": "sentry.integrations.discord.notify_action.DiscordNotifyServiceAction",
                "channel_id": "1112223334445556677",
                "tags": "environment",
                "uuid": "12345678-90ab-cdef-0123-456789abcdef",
            },
            {
                "server": "2",
                "id": "sentry.integrations.discord.notify_action.DiscordNotifyServiceAction",
                "channel_id": "99988877766555444333",
                "tags": "",
                "uuid": "22345678-90ab-cdef-0123-456789abcdef",
            },
        ]

        actions = build_notification_actions_from_rule_data_actions(action_data)

        self.assert_actions_migrated_correctly(actions, action_data, "server", "channel_id", None)

    @patch("sentry.workflow_engine.migration_helpers.rule_action.logger.error")
    def test_discord_action_migration_malformed(self, mock_logger):
        action_data = [
            # Missing required fields
            {
                "server": "1",
                "uuid": "12345678-90ab-cdef-0123-456789abcdef",
                "id": "sentry.integrations.discord.notify_action.DiscordNotifyServiceAction",
            },
            {
                "server": "1",
                "id": "sentry.integrations.discord.notify_action.DiscordNotifyServiceAction",
                "channel_id": "1112223334445556677",
                "tags": "environment",
                "uuid": "12345678-90ab-cdef-0123-456789abcdef",
            },
        ]

        actions = build_notification_actions_from_rule_data_actions(action_data)
        assert len(actions) == 1

        self.assert_actions_migrated_correctly(
            actions, action_data[1:], "server", "channel_id", None
        )

        # Assert the logger was called with the correct arguments
        mock_logger.assert_called_with(
            "Action blob is malformed: missing required fields",
            extra={
                "registry_id": "sentry.integrations.discord.notify_action.DiscordNotifyServiceAction",
                "action_uuid": "12345678-90ab-cdef-0123-456789abcdef",
                "missing_fields": ["channel_id"],
            },
        )

    def test_msteams_action_migration(self):
        action_data = [
            # MsTeams Action will  always include, channel and channel_id
            # It won't store anything in the data blob
            {
                "team": "12345",
                "id": "sentry.integrations.msteams.notify_action.MsTeamsNotifyServiceAction",
                "channel": "Bufo",
                "channel_id": "1:hksdhfdskfhsdfdhsk@thread.tacv2",
                "uuid": "10987654-3210-9876-5432-109876543210",
            },
            {
                "team": "230405",
                "id": "sentry.integrations.msteams.notify_action.MsTeamsNotifyServiceAction",
                "channel": "Sentry FE Non-Prod",
                "channel_id": "19:c3c894b8d4194fb1aa7f89da84bfcd69@thread.tacv2",
                "uuid": "4777a764-11fd-418c-b61b-533767424425",
            },
        ]

        actions = build_notification_actions_from_rule_data_actions(action_data)

        self.assert_actions_migrated_correctly(
            actions, action_data, "team", "channel_id", "channel"
        )

    @patch("sentry.workflow_engine.migration_helpers.rule_action.logger.error")
    def test_msteams_action_migration_malformed(self, mock_logger):
        action_data = [
            # Missing required fields
            {
                "team": "1",
                "uuid": "12345678-90ab-cdef-0123-456789abcdef",
                "id": "sentry.integrations.msteams.notify_action.MsTeamsNotifyServiceAction",
            },
            {
                "team": "1",
                "id": "sentry.integrations.msteams.notify_action.MsTeamsNotifyServiceAction",
                "channel": "Bufo",
                "channel_id": "1:hksdhfdskfhsdfdhsk@thread.tacv2",
                "uuid": "10987654-3210-9876-5432-109876543210",
            },
        ]

        actions = build_notification_actions_from_rule_data_actions(action_data)
        assert len(actions) == 1

        self.assert_actions_migrated_correctly(
            actions, action_data[1:], "team", "channel_id", "channel"
        )

        # Assert the logger was called with the correct arguments
        mock_logger.assert_called_with(
            "Action blob is malformed: missing required fields",
            extra={
                "registry_id": "sentry.integrations.msteams.notify_action.MsTeamsNotifyServiceAction",
                "action_uuid": "12345678-90ab-cdef-0123-456789abcdef",
                "missing_fields": ["channel_id", "channel"],
            },
        )

    def test_pagerduty_action_migration(self):
        action_data = [
            {
                "account": "123456",
                "id": "sentry.integrations.pagerduty.notify_action.PagerDutyNotifyServiceAction",
                "service": "91919",
                "uuid": "12345678-90ab-cdef-0123-456789abcdef",
            },
            {
                "account": "999999",
                "service": "19191",
                "id": "sentry.integrations.pagerduty.notify_action.PagerDutyNotifyServiceAction",
                "uuid": "9a8b7c6d-5e4f-3a2b-1c0d-9a8b7c6d5e4f",
                "severity": "warning",
            },
            {
                "account": "77777",
                "service": "57436",
                "severity": "info",
                "id": "sentry.integrations.pagerduty.notify_action.PagerDutyNotifyServiceAction",
                "uuid": "12345678-90ab-cdef-0123-456789abcdef",
            },
        ]

        actions = build_notification_actions_from_rule_data_actions(action_data)
        assert len(actions) == len(action_data)

        # Verify that default value is used when severity is not provided
        assert actions[0].data["priority"] == "default"
        # Verify that severity is mapped to priority
        assert actions[1].data["priority"] == "warning"
        assert actions[2].data["priority"] == "info"

        self.assert_actions_migrated_correctly(actions, action_data, "account", "service", None)

    def test_pagerduty_action_migration_malformed(self):
        action_data = [
            # Missing required fields
            {
                "account": "123456",
                "uuid": "12345678-90ab-cdef-0123-456789abcdef",
                "id": "sentry.integrations.pagerduty.notify_action.PagerDutyNotifyServiceAction",
            },
            {
                "account": "123456",
                "service": "91919",
                "id": "sentry.integrations.pagerduty.notify_action.PagerDutyNotifyServiceAction",
                "uuid": "12345678-90ab-cdef-0123-456789abcdef",
            },
        ]

        actions = build_notification_actions_from_rule_data_actions(action_data)
        assert len(actions) == 1

        self.assert_actions_migrated_correctly(actions, action_data[1:], "account", "service", None)

    def test_opsgenie_action_migration(self):
        action_data = [
            {
                "account": "11111",
                "id": "sentry.integrations.opsgenie.notify_action.OpsgenieNotifyTeamAction",
                "team": "2323213-bbbbbuuufffooobottt",
                "uuid": "87654321-0987-6543-2109-876543210987",
            },
            {
                "account": "123456",
                "team": "1234-bufo-bot",
                "priority": "P2",
                "id": "sentry.integrations.opsgenie.notify_action.OpsgenieNotifyTeamAction",
                "uuid": "12345678-90ab-cdef-0123-456789abcdef",
            },
            {
                "account": "999999",
                "team": "1234-bufo-bot-2",
                "priority": "P3",
                "id": "sentry.integrations.opsgenie.notify_action.OpsgenieNotifyTeamAction",
                "uuid": "01234567-89ab-cdef-0123-456789abcdef",
            },
        ]

        actions = build_notification_actions_from_rule_data_actions(action_data)
        assert len(actions) == len(action_data)

        # Verify that default value is used when priority is not provided
        assert actions[0].data["priority"] == "P3"
        # Verify that priority is mapped to priority
        assert actions[1].data["priority"] == "P2"
        assert actions[2].data["priority"] == "P3"

        self.assert_actions_migrated_correctly(actions, action_data, "account", "team", None)

    def test_opsgenie_action_migration_malformed(self):
        action_data = [
            # Missing required fields
            {
                "account": "123456",
                "uuid": "12345678-90ab-cdef-0123-456789abcdef",
                "id": "sentry.integrations.opsgenie.notify_action.OpsgenieNotifyTeamAction",
            },
            {
                "account": "123456",
                "team": "1234-bufo-bot",
                "id": "sentry.integrations.opsgenie.notify_action.OpsgenieNotifyTeamAction",
                "uuid": "12345678-90ab-cdef-0123-456789abcdef",
            },
        ]

        actions = build_notification_actions_from_rule_data_actions(action_data)
        assert len(actions) == 1

        self.assert_actions_migrated_correctly(actions, action_data[1:], "account", "team", None)

    def test_github_action_migration(self):
        # Includes both, Github and Github Enterprise. We currently don't have any rules configured for Github Enterprise.
        # The Github Enterprise action should have the same shape as the Github action.
        action_data = [
            {
                "integration": "123456",
                "id": "sentry.integrations.github.notify_action.GitHubCreateTicketAction",
                "dynamic_form_fields": [
                    {
                        "name": "repo",
                        "label": "GitHub Repository",
                        "type": "select",
                        "default": "bufobot/bufo-bot",
                        "choices": [
                            ["bufobot/bufo-bot", "bufo-bot"],
                            ["bufobot/bufo-bot-2", "bufo-bot-2"],
                            [
                                "bufobot/bufo-bot-3",
                                {
                                    "key": "bufobot/bufo-bot-3",
                                    "ref": None,
                                    "props": {
                                        "children": [
                                            {
                                                "key": "bufobot/bufo-bot-3",
                                                "ref": None,
                                                "props": {
                                                    "title": {
                                                        "key": "bufobot/bufo-bot-3",
                                                        "ref": None,
                                                        "_owner": None,
                                                    },
                                                    "size": "xs",
                                                },
                                            },
                                            " ",
                                            "bufo-bot-3",
                                        ]
                                    },
                                    "_owner": None,
                                },
                            ],
                        ],
                        "url": "/extensions/github/search/bufobot/123456/",
                        "updatesForm": True,
                        "required": True,
                    },
                    {
                        "name": "assignee",
                        "label": "Assignee",
                        "default": "",
                        "type": "select",
                        "required": False,
                        "choices": [
                            ["", "Unassigned"],
                            ["bufo-bot", "bufo-bot"],
                            ["bufo-bot-2", "bufo-bot-2"],
                            ["bufo-bot-3", "bufo-bot-3"],
                        ],
                    },
                    {
                        "name": "labels",
                        "label": "Labels",
                        "default": [],
                        "type": "select",
                        "multiple": True,
                        "required": False,
                        "choices": [
                            ["bug", "bug"],
                            ["documentation", "documentation"],
                            ["duplicate", "duplicate"],
                            ["enhancement", "enhancement"],
                            ["good first issue", "good first issue"],
                            ["invalid", "invalid"],
                            ["question", "question"],
                            ["security", "security"],
                        ],
                    },
                ],
                "repo": "bufobot/bufo-bot",
                "labels": ["bug", "documentation"],
                "uuid": "12345678-90ab-cdef-0123-456789abcdef",
            },
            {
                "integration": "00000",
                "id": "sentry.integrations.github.notify_action.GitHubCreateTicketAction",
                "dynamic_form_fields": [
                    {
                        "name": "repo",
                        "label": "GitHub Repository",
                        "type": "select",
                        "default": "bufobot/bufo-bot-3",
                        "choices": [
                            [
                                "bufobot/bufo-bot-3",
                                "bufo-bot-3",
                            ]
                        ],
                        "url": "/extensions/github/search/bufobot/00000/",
                        "updatesForm": True,
                        "required": True,
                    },
                    {
                        "name": "assignee",
                        "label": "Assignee",
                        "default": "",
                        "type": "select",
                        "required": False,
                        "choices": [["", "Unassigned"], ["bufo-bot", "bufo-bot"]],
                    },
                    {
                        "name": "labels",
                        "label": "Labels",
                        "default": [],
                        "type": "select",
                        "multiple": True,
                        "required": False,
                        "choices": [
                            ["bug", "bug"],
                            ["documentation", "documentation"],
                            ["duplicate", "duplicate"],
                            ["enhancement", "enhancement"],
                            ["good first issue", "good first issue"],
                            ["help wanted", "help wanted"],
                            ["invalid", "invalid"],
                            ["question", "question"],
                            ["wontfix", "wontfix"],
                        ],
                    },
                ],
                "repo": "bufobot/bufo-bot-3",
                "assignee": "bufo-bot-3",
                "labels": ["bug", "documentation"],
                "uuid": "12345678-90ab-cdef-0123-456789abcdef",
            },
            {
                "integration": "22222",
                "id": "sentry.integrations.github_enterprise.notify_action.GitHubEnterpriseCreateTicketAction",
                "dynamic_form_fields": [
                    {
                        "name": "repo",
                        "label": "GitHub Repository",
                        "type": "select",
                        "default": "bufobot/bufo-bot-3",
                        "choices": [
                            ["bufobot/bufo-bot-3", "bufo-bot-3"],
                            [
                                "bufobot/bufo-bot-3",
                                {
                                    "key": "bufobot/bufo-bot-3",
                                    "ref": None,
                                    "props": {
                                        "children": [
                                            {
                                                "key": "bufobot/bufo-bot-3",
                                                "ref": None,
                                                "props": {
                                                    "title": {
                                                        "key": "bufobot/bufo-bot-3",
                                                        "ref": None,
                                                        "props": {
                                                            "children": {
                                                                "key": "5",
                                                                "ref": None,
                                                                "_owner": None,
                                                            }
                                                        },
                                                        "_owner": None,
                                                    },
                                                    "size": "xs",
                                                },
                                                "_owner": None,
                                            },
                                            " ",
                                            "Project_topup",
                                        ]
                                    },
                                    "_owner": None,
                                },
                            ],
                        ],
                        "url": "/extensions/github/search/bufobot/22222/",
                        "updatesForm": True,
                        "required": True,
                    },
                    {
                        "name": "assignee",
                        "label": "Assignee",
                        "default": "",
                        "type": "select",
                        "required": False,
                        "choices": [
                            ["", "Unassigned"],
                            ["bufo-bot", "bufo-bot"],
                            ["bufo-bot-2", "bufo-bot-2"],
                            ["bufo-bot-3", "bufo-bot-3"],
                        ],
                    },
                    {
                        "name": "labels",
                        "label": "Labels",
                        "default": [],
                        "type": "select",
                        "multiple": True,
                        "required": False,
                        "choices": [
                            ["bug", "bug"],
                            ["documentation", "documentation"],
                            ["duplicate", "duplicate"],
                            ["enhancement", "enhancement"],
                            ["good first issue", "good first issue"],
                            ["help wanted", "help wanted"],
                            ["invalid", "invalid"],
                            ["question", "question"],
                        ],
                    },
                ],
                "repo": "bufobot/bufo-bot-3",
                "assignee": "",
                "labels": [],
                "uuid": "12345678-90ab-cdef-0123-456789abcdef",
            },
        ]

        actions = build_notification_actions_from_rule_data_actions(action_data)

        self.assert_actions_migrated_correctly(actions, action_data, "integration", None, None)

    def test_github_action_migration_malformed(self):
        action_data = [
            # Missing required fields
            {
                "uuid": "12345678-90ab-cdef-0123-456789abcdef",
                "id": "sentry.integrations.github.notify_action.GitHubCreateTicketAction",
            },
        ]

        actions = build_notification_actions_from_rule_data_actions(action_data)
        assert len(actions) == 0

    def test_azure_devops_migration(self):
        action_data = [
            {
                "integration": "999999",
                "id": "sentry.integrations.vsts.notify_action.AzureDevopsCreateTicketAction",
                "dynamic_form_fields": [
                    {
                        "name": "project",
                        "required": True,
                        "type": "choice",
                        "choices": [
                            ["12345678-90ab-cdef-0123-456789abcdef", "Test Octo"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "Octopus"],
                        ],
                        "defaultValue": "12345678-90ab-cdef-0123-456789abcdef",
                        "label": "Project",
                        "placeholder": "12345678-90ab-cdef-0123-456789abcdef",
                        "updatesForm": True,
                    },
                    {
                        "name": "work_item_type",
                        "required": True,
                        "type": "choice",
                        "choices": [
                            ["Microsoft.VSTS.WorkItemTypes.Bug", "Bug"],
                            ["Microsoft.VSTS.WorkItemTypes.Epic", "Epic"],
                            ["Microsoft.VSTS.WorkItemTypes.Feature", "Feature"],
                            ["Microsoft.VSTS.WorkItemTypes.UserStory", "User Story"],
                            ["Microsoft.VSTS.WorkItemTypes.TestCase", "Test Case"],
                            ["Microsoft.VSTS.WorkItemTypes.SharedStep", "Shared Steps"],
                            ["Microsoft.VSTS.WorkItemTypes.SharedParameter", "Shared Parameter"],
                            [
                                "Microsoft.VSTS.WorkItemTypes.CodeReviewRequest",
                                "Code Review Request",
                            ],
                            [
                                "Microsoft.VSTS.WorkItemTypes.CodeReviewResponse",
                                "Code Review Response",
                            ],
                            ["Microsoft.VSTS.WorkItemTypes.FeedbackRequest", "Feedback Request"],
                            ["Microsoft.VSTS.WorkItemTypes.FeedbackResponse", "Feedback Response"],
                            ["Microsoft.VSTS.WorkItemTypes.TestPlan", "Test Plan"],
                            ["Microsoft.VSTS.WorkItemTypes.TestSuite", "Test Suite"],
                            ["Microsoft.VSTS.WorkItemTypes.Task", "Task"],
                        ],
                        "defaultValue": "Microsoft.VSTS.WorkItemTypes.Bug",
                        "label": "Work Item Type",
                        "placeholder": "Bug",
                    },
                ],
                "project": "12345678-90ab-cdef-0123-456789abcdef",
                "work_item_type": "Microsoft.VSTS.WorkItemTypes.Bug",
                "uuid": "7a48abdb-60d7-4d1c-ab00-0eedb2189933",
            },
            {
                "integration": "123456",
                "id": "sentry.integrations.vsts.notify_action.AzureDevopsCreateTicketAction",
                "dynamic_form_fields": [
                    {
                        "name": "project",
                        "required": True,
                        "type": "choice",
                        "choices": [
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-125"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-121"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-122"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-127"],
                            ["99999999-90ab-cdef-0123-456789abcdef", "O-129"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-131"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-128"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-107"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-120"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-123"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-119"],
                            ["cb72f217-bcb2-495c-b7ad-d6883e696990", "O-116"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-115"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "Alpha Octo"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-126"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-102"],
                            ["23ff99ca-92f2-492f-b8a1-d13ed66c465c", "O-124"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-114"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-112"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-108"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-000"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-101"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-104"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-110"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-111"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-130"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-117"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "Design"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-118"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-109"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-106"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-103"],
                            ["12345678-90ab-cdef-0123-456789abcdef", "O-105"],
                        ],
                        "defaultValue": "12345678-90ab-cdef-0123-456789abcdef",
                        "label": "Project",
                        "placeholder": "12345678-90ab-cdef-0123-456789abcdef",
                        "updatesForm": True,
                    },
                    {
                        "name": "work_item_type",
                        "required": True,
                        "type": "choice",
                        "choices": [
                            ["Microsoft.VSTS.WorkItemTypes.Bug", "Bug"],
                            ["Microsoft.VSTS.WorkItemTypes.Epic", "Epic"],
                            ["Microsoft.VSTS.WorkItemTypes.Feature", "Feature"],
                            [
                                "Microsoft.VSTS.WorkItemTypes.ProductBacklogItem",
                                "Product Backlog Item",
                            ],
                            ["Microsoft.VSTS.WorkItemTypes.TestCase", "Test Case"],
                            ["Microsoft.VSTS.WorkItemTypes.SharedStep", "Shared Steps"],
                            ["Microsoft.VSTS.WorkItemTypes.SharedParameter", "Shared Parameter"],
                            [
                                "Microsoft.VSTS.WorkItemTypes.CodeReviewRequest",
                                "Code Review Request",
                            ],
                            [
                                "Microsoft.VSTS.WorkItemTypes.CodeReviewResponse",
                                "Code Review Response",
                            ],
                            ["Microsoft.VSTS.WorkItemTypes.FeedbackRequest", "Feedback Request"],
                            ["Microsoft.VSTS.WorkItemTypes.FeedbackResponse", "Feedback Response"],
                            ["Microsoft.VSTS.WorkItemTypes.TestPlan", "Test Plan"],
                            ["Microsoft.VSTS.WorkItemTypes.TestSuite", "Test Suite"],
                            ["Microsoft.VSTS.WorkItemTypes.Task", "Task"],
                        ],
                        "defaultValue": "Microsoft.VSTS.WorkItemTypes.Bug",
                        "label": "Work Item Type",
                        "placeholder": "Bug",
                    },
                ],
                "project": "23ff99ca-92f2-492f-b8a1-d13ed66c465c",
                "work_item_type": "Microsoft.VSTS.WorkItemTypes.Bug",
                "uuid": "4d42b17d-911d-4085-be7f-cc5f32d66371",
            },
        ]

        actions = build_notification_actions_from_rule_data_actions(action_data)
        self.assert_actions_migrated_correctly(actions, action_data, "integration", None, None)

    def test_azure_devops_migration_malformed(self):
        action_data = [
            # Missing required fields
            {
                "uuid": "12345678-90ab-cdef-0123-456789abcdef",
                "id": "sentry.integrations.vsts.notify_action.AzureDevopsCreateTicketAction",
            },
        ]

        actions = build_notification_actions_from_rule_data_actions(action_data)
        assert len(actions) == 0

    def test_jira_action_migration(self):
        action_data = [
            {
                "integration": "12345",
                "id": "sentry.integrations.jira.notify_action.JiraCreateTicketAction",
                "dynamic_form_fields": [
                    {
                        "name": "project",
                        "label": "Jira Project",
                        "choices": [["10001", "PROJ1"], ["10002", "PROJ2"], ["10003", "PROJ3"]],
                        "default": "10001",
                        "type": "select",
                        "updatesForm": True,
                    },
                    {
                        "name": "issuetype",
                        "label": "Issue Type",
                        "default": "10001",
                        "type": "select",
                        "choices": [["10001", "Story"], ["10002", "Bug"], ["10003", "Task"]],
                        "updatesForm": True,
                        "required": True,
                    },
                    {
                        "label": "Fix versions",
                        "required": False,
                        "multiple": True,
                        "choices": [],
                        "default": "",
                        "type": "select",
                        "name": "fixVersions",
                    },
                    {
                        "label": "Assignee",
                        "required": False,
                        "url": "/extensions/jira/search/example/12345/",
                        "choices": [["user123", "John Doe"]],
                        "type": "select",
                        "name": "assignee",
                    },
                ],
                "description": "This will be generated from the Sentry Issue details.",
                "project": "10001",
                "issuetype": "10001",
                "assignee": "user123",
                "reporter": "user123",
                "parent": "PROJ-123",
                "labels": "Sentry",
                "uuid": "11111111-1111-1111-1111-111111111111",
            },
            {
                "integration": "12345",
                "id": "sentry.integrations.jira.notify_action.JiraCreateTicketAction",
                "dynamic_form_fields": [
                    {
                        "name": "project",
                        "label": "Jira Project",
                        "choices": [["10001", "PROJ1"], ["10002", "PROJ2"], ["10003", "PROJ3"]],
                        "default": "10001",
                        "type": "select",
                        "updatesForm": True,
                    },
                    {
                        "name": "issuetype",
                        "label": "Issue Type",
                        "default": "10001",
                        "type": "select",
                        "choices": [["10001", "Task"], ["10002", "Bug"], ["10003", "Story"]],
                        "updatesForm": True,
                        "required": True,
                    },
                    {
                        "label": "Priority",
                        "required": False,
                        "choices": [
                            ["1", "Highest"],
                            ["2", "High"],
                            ["3", "Medium"],
                            ["4", "Low"],
                            ["5", "Lowest"],
                        ],
                        "type": "select",
                        "name": "priority",
                        "default": "",
                    },
                    {
                        "label": "Team",
                        "required": False,
                        "choices": [
                            ["Team A", "Team A"],
                            ["Team B", "Team B"],
                            ["Team C", "Team C"],
                        ],
                        "type": "select",
                        "name": "customfield_10253",
                    },
                    {
                        "label": "Platform",
                        "required": False,
                        "multiple": True,
                        "choices": [
                            ["iOS", "iOS"],
                            ["Android", "Android"],
                            ["Backend", "Backend"],
                            ["Frontend", "Frontend"],
                        ],
                        "default": "",
                        "type": "select",
                        "name": "customfield_10285",
                    },
                ],
                "description": "This will be generated from the Sentry Issue details.",
                "project": "10001",
                "issuetype": "10001",
                "priority": "",
                "labels": "",
                "reporter": "user123",
                "customfield_10253": "Team A",
                "customfield_10285": ["Backend"],
                "customfield_10290": "",
                "customfield_10301": "",
                "customfield_10315": "",
                "versions": "",
                "uuid": "12345678-1234-5678-1234-567812345678",
            },
            {
                "integration": "123456",
                "id": "sentry.integrations.jira.notify_action.JiraCreateTicketAction",
                "dynamic_form_fields": [
                    {
                        "name": "project",
                        "label": "Jira Project",
                        "choices": [["10000", "PROJ1"], ["10003", "PROJ2"]],
                        "default": "10000",
                        "type": "select",
                        "updatesForm": True,
                    },
                    {
                        "name": "issuetype",
                        "label": "Issue Type",
                        "default": "10031",
                        "type": "select",
                        "choices": [
                            ["10001", "Task"],
                            ["10002", "Epic"],
                            ["10003", "Subtask"],
                            ["10005", "Question"],
                            ["10018", "Wireframe"],
                            ["10028", "Folder"],
                            ["10029", "Story"],
                            ["10031", "Bug"],
                        ],
                        "updatesForm": True,
                        "required": True,
                    },
                    {
                        "label": "Assignee",
                        "required": False,
                        "url": "/extensions/jira/search/organization/123456/",
                        "choices": [],
                        "type": "select",
                        "name": "assignee",
                    },
                    {
                        "label": "Development",
                        "required": False,
                        "type": "text",
                        "name": "customfield_10000",
                    },
                    {
                        "label": "Team",
                        "required": False,
                        "type": "text",
                        "name": "customfield_10001",
                    },
                    {
                        "label": "Story point estimate",
                        "required": False,
                        "type": "text",
                        "name": "customfield_10016",
                    },
                    {
                        "label": "Rank",
                        "required": False,
                        "type": "text",
                        "name": "customfield_10019",
                    },
                    {
                        "label": "Flagged",
                        "required": False,
                        "multiple": True,
                        "choices": [["Impediment", "Impediment"]],
                        "default": "",
                        "type": "select",
                        "name": "customfield_10021",
                    },
                    {
                        "label": "Design",
                        "required": False,
                        "multiple": True,
                        "choices": [],
                        "default": "",
                        "type": "select",
                        "name": "customfield_10036",
                    },
                    {
                        "label": "Description",
                        "required": False,
                        "type": "text",
                        "name": "description",
                    },
                    {
                        "label": "Restrict to",
                        "required": False,
                        "type": "text",
                        "name": "issuerestriction",
                    },
                    {
                        "label": "Labels",
                        "required": False,
                        "type": "text",
                        "name": "labels",
                        "default": "",
                    },
                    {
                        "label": "Parent",
                        "required": False,
                        "url": "/extensions/jira/search/organization/123456/",
                        "choices": [],
                        "type": "select",
                        "name": "parent",
                    },
                    {
                        "label": "Reporter",
                        "required": True,
                        "url": "/extensions/jira/search/organization/123456/",
                        "choices": [["user123", "Test User"]],
                        "type": "select",
                        "name": "reporter",
                    },
                ],
                "description": "This will be generated from the Sentry Issue details.",
                "project": "10000",
                "issuetype": "10031",
                "reporter": "user123",
                "uuid": "00000000-0000-0000-0000-000000000000",
            },
        ]

        actions = build_notification_actions_from_rule_data_actions(action_data)
        self.assert_actions_migrated_correctly(actions, action_data, "integration", None, None)

    def test_jira_action_migration_malformed(self):
        action_data = [
            # Missing required fields
            {
                "uuid": "12345678-90ab-cdef-0123-456789abcdef",
                "id": "sentry.integrations.jira.notify_action.JiraCreateTicketAction",
            },
            # Empty additional fields
            {
                "integration": "12345",
                "id": "sentry.integrations.jira.notify_action.JiraCreateTicketAction",
                "project": "10001",
                "issuetype": "10001",
                "reporter": "user123",
                "uuid": "11111111-1111-1111-1111-111111111111",
                "customfield_10253": "",
                "customfield_10285": [],
                "customfield_10290": "",
                "customfield_10301": "",
                "customfield_10315": "",
            },
        ]

        actions = build_notification_actions_from_rule_data_actions(action_data)
        # Only the second action should be created since it has required fields
        assert len(actions) == 1

        # Verify empty additional fields are handled correctly
        action = actions[0]
        assert action.data.get("additional_fields") == {}

    def test_jira_server_action_migration(self):
        action_data = [
            {
                "integration": "123456",
                "id": "sentry.integrations.jira_server.notify_action.JiraServerCreateTicketAction",
                "dynamic_form_fields": [
                    {
                        "name": "project",
                        "label": "Jira Project",
                        "choices": [["10001", "PROJ1"], ["10002", "PROJ2"], ["10003", "PROJ3"]],
                        "default": "10001",
                        "type": "select",
                        "updatesForm": True,
                    },
                    {
                        "name": "issuetype",
                        "label": "Issue Type",
                        "default": "1",
                        "type": "select",
                        "choices": [["1", "Defect"], ["3", "Task"], ["7", "Epic"], ["8", "Story"]],
                        "updatesForm": True,
                        "required": True,
                    },
                    {
                        "label": "Priority",
                        "required": False,
                        "choices": [["2", "Blocker"], ["3", "High"], ["6", "Medium"], ["4", "Low"]],
                        "type": "select",
                        "name": "priority",
                        "default": "",
                    },
                    {
                        "label": "Fix Version/s",
                        "required": False,
                        "multiple": True,
                        "choices": [
                            ["81527", "Version 1.0"],
                            ["81529", "Version 1.1"],
                            ["82011", "Version 2.0"],
                        ],
                        "default": "",
                        "type": "select",
                        "name": "fixVersions",
                    },
                    {
                        "label": "Component/s",
                        "required": False,
                        "multiple": True,
                        "choices": [
                            ["11841", "Backend"],
                            ["12385", "Frontend"],
                            ["12422", "Mobile"],
                        ],
                        "default": "",
                        "type": "select",
                        "name": "components",
                    },
                    {
                        "label": "Description",
                        "required": True,
                        "type": "text",
                        "name": "description",
                    },
                    {
                        "label": "Labels",
                        "required": False,
                        "type": "text",
                        "name": "labels",
                        "default": "",
                    },
                    {
                        "label": "Reporter",
                        "required": True,
                        "url": "/extensions/jira-server/search/org/123456/",
                        "choices": [["user123", "Test User"]],
                        "type": "select",
                        "name": "reporter",
                    },
                ],
                "description": "This will be generated from the Sentry Issue details.",
                "project": "10001",
                "issuetype": "1",
                "priority": "3",
                "components": ["11841"],
                "reporter": "user123",
                "uuid": "11111111-1111-1111-1111-111111111111",
            },
            {
                "integration": "123456",
                "id": "sentry.integrations.jira_server.notify_action.JiraServerCreateTicketAction",
                "dynamic_form_fields": [
                    {
                        "name": "project",
                        "label": "Jira Project",
                        "choices": [["20001", "TEAM1"], ["20002", "TEAM2"]],
                        "default": "20001",
                        "type": "select",
                        "updatesForm": True,
                    },
                    {
                        "name": "issuetype",
                        "label": "Issue Type",
                        "default": "8",
                        "type": "select",
                        "choices": [["1", "Defect"], ["8", "Story"]],
                        "updatesForm": True,
                        "required": True,
                    },
                ],
                "description": "This will be generated from the Sentry Issue details.",
                "project": "20001",
                "issuetype": "8",
                "reporter": "user123",
                "uuid": "22222222-2222-2222-2222-222222222222",
            },
        ]

        actions = build_notification_actions_from_rule_data_actions(action_data)
        self.assert_actions_migrated_correctly(actions, action_data, "integration", None, None)

    def test_jira_server_action_migration_malformed(self):
        action_data = [
            # Missing required fields
            {
                "uuid": "12345678-90ab-cdef-0123-456789abcdef",
                "id": "sentry.integrations.jira_server.notify_action.JiraServerCreateTicketAction",
            },
            # Empty additional fields
            {
                "integration": "123456",
                "id": "sentry.integrations.jira_server.notify_action.JiraServerCreateTicketAction",
                "project": "10001",
                "issuetype": "1",
                "reporter": "user123",
                "uuid": "11111111-1111-1111-1111-111111111111",
                "priority": "",
                "components": [],
                "fixVersions": [],
            },
        ]

        actions = build_notification_actions_from_rule_data_actions(action_data)
        # Only the second action should be created since it has required fields
        assert len(actions) == 1

        # Verify empty additional fields are handled correctly
        action = actions[0]
        assert action.data.get("additional_fields") == {}

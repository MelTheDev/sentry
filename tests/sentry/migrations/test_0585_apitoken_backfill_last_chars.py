from sentry.testutils.cases import TestMigrations


class NameLastCharsApiTokenMigrationTest(TestMigrations):
    migrate_from = "0584_apitoken_add_name_and_last_four"
    migrate_to = "0585_apitoken_backfill_last_chars"
    connection = "control"

    def setup_before_migration(self, apps):
        ApiToken = apps.get_model("sentry", "ApiToken")
        self.api_token = ApiToken.objects.create(
            user_id=self.user.id,
            refresh_token=None,
        )
        self.api_token.save()

    def test(self):
        from sentry.models.apitoken import ApiToken

        api_tokens = ApiToken.objects.all()
        for api_token in api_tokens:
            assert api_token.name is None
            assert api_token.token_last_characters == api_token.token[-4:]

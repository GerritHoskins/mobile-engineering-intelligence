# Vendor credentials for ingestion. Terraform creates the secrets EMPTY: their
# values are set by a person with `aws secretsmanager put-secret-value`, so no
# token ever passes through Terraform state, the repo or an assistant.
# recovery_window_in_days = 0 lets a destroyed dev stack be re-applied at once.

locals {
  # env var name read by app/connectors/clients.py -> secret name suffix
  credentials = {
    SENTRY_READ_TOKEN = "sentry-read-token"
    JIRA_EMAIL        = "jira-email"
    JIRA_API_TOKEN    = "jira-api-token"
    GITHUB_READ_TOKEN = "github-read-token"
  }
}

resource "aws_secretsmanager_secret" "vendor" {
  for_each = local.credentials

  name                    = "${var.name}/${each.value}"
  description             = "Ingestion credential ${each.key} (value set by hand, never by Terraform)"
  recovery_window_in_days = 0
}

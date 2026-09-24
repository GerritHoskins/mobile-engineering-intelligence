# An AWS account can hold only one GitHub OIDC provider; reuse it if it exists.
resource "aws_iam_openid_connect_provider" "github" {
  count = var.existing_provider_arn == null ? 1 : 0

  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

locals {
  provider_arn = coalesce(var.existing_provider_arn, one(aws_iam_openid_connect_provider.github[*].arn))
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Only workflows running on this repository's main branch. The immutable
    # subject embeds owner/repo IDs, so a renamed or re-created repository with
    # the same name cannot assume this role.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${var.subject_prefix}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "image_push" {
  name               = "${var.name}-github-image-push"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

data "aws_iam_policy_document" "ecr_push" {
  statement {
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [var.ecr_repository_arn]
  }
}

resource "aws_iam_role_policy" "ecr_push" {
  name   = "ecr-push"
  role   = aws_iam_role.image_push.id
  policy = data.aws_iam_policy_document.ecr_push.json
}

# =============================================================================
# GitHub Actions OIDC Identity Provider
# =============================================================================
# Allows GitHub Actions workflows to authenticate with AWS via OIDC
# (no long-lived credentials needed).
# =============================================================================

resource "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"

  thumbprint_list = [
    "1b511abead59c6ce207077c0bf0e0043b1382612"
  ]

  client_id_list = ["sts.amazonaws.com"]

  tags = merge(local.common_tags, {
    Name = "${local.name}-github-oidc"
  })
}

# ---------------------------------------------------------------------------
# IAM Role that GitHub Actions can assume
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "github_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:*"]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name               = "${local.name}-github-actions-role"
  description        = "Role assumed by GitHub Actions CI/CD for driftwatch"
  assume_role_policy = data.aws_iam_policy_document.github_assume_role.json
  tags = merge(local.common_tags, {
    Name = "${local.name}-github-actions-role"
  })
}

# ---------------------------------------------------------------------------
# Inline policy: ECR push + ECS deploy permissions
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "github_actions_deploy" {
  statement {
    sid    = "ECRPush"
    effect = "Allow"
    actions = [
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
      "ecr:BatchCheckLayerAvailability",
      "ecr:PutImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:GetAuthorizationToken",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "ECSDeploy"
    effect = "Allow"
    actions = [
      "ecs:DescribeTaskDefinition",
      "ecs:RegisterTaskDefinition",
      "ecs:DescribeServices",
      "ecs:UpdateService",
      "ecs:ListClusters",
      "ecs:ListTaskDefinitions",
      "ecs:ListServices",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "PassRole"
    effect = "Allow"
    actions = [
      "iam:PassRole",
    ]
    resources = [
      module.ecs.execution_role_arn,
      module.ecs.task_role_arn,
    ]
  }

  statement {
    sid    = "ALBDescribe"
    effect = "Allow"
    actions = [
      "elasticloadbalancing:DescribeTargetGroups",
      "elasticloadbalancing:DescribeTargetHealth",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_actions_deploy" {
  name   = "deploy"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.github_actions_deploy.json
}

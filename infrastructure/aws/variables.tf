variable "region" {
  description = "AWS region for all regional resources."
  type        = string
  default     = "us-east-1"
}

variable "env" {
  description = "Environment label baked into resource names and tags."
  type        = string
  default     = "prod"
}

variable "expected_account_id" {
  description = "AWS account ID this folder is expected to apply against. Sanity check; matches the prod account."
  type        = string
  default     = "522096685539"
}

variable "github_repo" {
  description = "GitHub repository in 'owner/repo' format. Used by the GHA deploy role's trust policy."
  type        = string

  validation {
    condition     = can(regex("^[^/[:space:]]+/[^/[:space:]]+$", var.github_repo))
    error_message = "github_repo must be in 'owner/repo' format (no slashes or whitespace in either segment)."
  }
}

variable "github_branch" {
  description = "Branch that triggers production deploys. The GHA trust policy is scoped to this branch only."
  type        = string
  default     = "main"
}

variable "k8s_namespace" {
  description = "Kubernetes namespace for service ServiceAccounts that consume IRSA roles."
  type        = string
  default     = "maisys"
}

variable "services" {
  description = "List of MAISYS services. One ECR repository and one IRSA role are created per service."
  type        = list(string)
  default = [
    "api-gateway",
    "auth-service",
    "chatbot-service",
    "drug-service",
    "symptom-service",
    "lab-service",
    "research-service",
    "translation-service",
    "export-service",
    "safety-service",
    "notification-service",
    "model-router-service",
    "admin-service",
    "frontend",
  ]
}

variable "secret_names" {
  description = "List of Secrets Manager secrets to create as shells. Values are populated separately."
  type        = list(string)
  default = [
    "kaggle-api-key",
    "hf-token",
    "jwt-secret",
    "postgres-password",
    "redis-password",
    "llm-openai-api-key",
    "llm-anthropic-api-key",
    "infermedica-api-key",
    "rxnorm-credentials",
    "serpapi-key",
  ]
}

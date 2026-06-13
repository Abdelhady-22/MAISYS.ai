# ──────────────────────────────────────────────────────────────────────────
# GKE workload service account
# ──────────────────────────────────────────────────────────────────────────
# Identity assumed by application pods via GKE Workload Identity. The
# Kubernetes-side annotations on each ServiceAccount are applied through the
# k8s manifests (overlay per env), not from terraform.
resource "google_service_account" "gke_workload" {
  account_id   = "maisys-gke-workload-${var.env}"
  display_name = "MAISYS GKE workload SA (${var.env})"
  description  = "Identity assumed by application pods via GKE Workload Identity."
}

# Broad starting permissions — narrow per-service in follow-up tasks as
# specific apps reach production.
resource "google_project_iam_member" "gke_workload_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.gke_workload.email}"
}

resource "google_project_iam_member" "gke_workload_storage_object_user" {
  project = var.project_id
  role    = "roles/storage.objectUser"
  member  = "serviceAccount:${google_service_account.gke_workload.email}"
}

# ──────────────────────────────────────────────────────────────────────────
# GitHub Actions deploy service account
# ──────────────────────────────────────────────────────────────────────────
resource "google_service_account" "gha_deploy" {
  account_id   = "maisys-gha-deploy-${var.env}"
  display_name = "MAISYS GitHub Actions deploy SA (${var.env})"
  description  = "Federated identity for GitHub Actions to push images and deploy to GKE."
}

resource "google_project_iam_member" "gha_deploy_artifact_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.gha_deploy.email}"
}

resource "google_project_iam_member" "gha_deploy_gke_developer" {
  project = var.project_id
  role    = "roles/container.developer"
  member  = "serviceAccount:${google_service_account.gha_deploy.email}"
}

# Needed by `gcloud container clusters get-credentials` so the workflow can
# build a kubeconfig pointing at the cluster.
resource "google_project_iam_member" "gha_deploy_cluster_viewer" {
  project = var.project_id
  role    = "roles/container.clusterViewer"
  member  = "serviceAccount:${google_service_account.gha_deploy.email}"
}

# ──────────────────────────────────────────────────────────────────────────
# Workload Identity Federation for GitHub Actions OIDC
# ──────────────────────────────────────────────────────────────────────────
# No long-lived service account keys are issued. GitHub Actions presents an
# OIDC token; GCP validates it against this provider; the workflow then
# impersonates google_service_account.gha_deploy for the duration of the run.
resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "maisys-github-pool-${var.env}"
  display_name              = "MAISYS GitHub Pool (${var.env})"
  description               = "OIDC federation pool for GitHub Actions in ${var.github_repo}."
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub OIDC"
  description                        = "Accepts GitHub Actions OIDC tokens scoped to ${var.github_repo}."

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.actor"      = "assertion.actor"
    "attribute.ref"        = "assertion.ref"
  }

  # Hard restriction: only tokens issued for THIS repo can use the provider.
  # Without this, any GitHub workflow on any repo could obtain GCP credentials.
  attribute_condition = "assertion.repository == \"${var.github_repo}\""
}

# Allow the workload identity, scoped to the configured GitHub repo, to
# impersonate the deploy SA.
resource "google_service_account_iam_member" "gha_workload_identity_binding" {
  service_account_id = google_service_account.gha_deploy.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}

output "id" {
  description = "Repository resource ID."
  value       = google_artifact_registry_repository.this.id
}

output "name" {
  description = "Repository ID (the short name)."
  value       = google_artifact_registry_repository.this.repository_id
}

output "url" {
  description = "Docker-pullable repository URL (without trailing image name)."
  value = format(
    "%s-docker.pkg.dev/%s/%s",
    google_artifact_registry_repository.this.location,
    google_artifact_registry_repository.this.project,
    google_artifact_registry_repository.this.repository_id,
  )
}

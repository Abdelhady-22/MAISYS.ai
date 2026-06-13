output "id" {
  description = "Full secret resource ID (projects/<project>/secrets/<name>)."
  value       = google_secret_manager_secret.this.id
}

output "name" {
  description = "Secret short name."
  value       = google_secret_manager_secret.this.secret_id
}

output "id" {
  description = "Bucket resource ID."
  value       = google_storage_bucket.this.id
}

output "name" {
  description = "Bucket name."
  value       = google_storage_bucket.this.name
}

output "url" {
  description = "Cloud-agnostic bucket URL (gs:// for GCS)."
  value       = "gs://${google_storage_bucket.this.name}"
}

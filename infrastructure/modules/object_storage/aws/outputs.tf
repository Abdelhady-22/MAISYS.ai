output "id" {
  description = "S3 bucket name (S3 uses the bucket name as the resource ID)."
  value       = aws_s3_bucket.this.id
}

output "name" {
  description = "Bucket name."
  value       = aws_s3_bucket.this.bucket
}

output "url" {
  description = "Cloud-agnostic bucket URL (s3:// for AWS)."
  value       = "s3://${aws_s3_bucket.this.bucket}"
}

output "arn" {
  description = "Bucket ARN."
  value       = aws_s3_bucket.this.arn
}

output "regional_domain_name" {
  description = "AWS-specific: regional S3 domain name for direct HTTPS access."
  value       = aws_s3_bucket.this.bucket_regional_domain_name
}

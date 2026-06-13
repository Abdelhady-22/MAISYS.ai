output "id" {
  description = "ECR repository resource ID."
  value       = aws_ecr_repository.this.id
}

output "name" {
  description = "Repository name."
  value       = aws_ecr_repository.this.name
}

output "url" {
  description = "Docker-pullable repository URL (azurerm/google call this 'login_server' / 'url')."
  value       = aws_ecr_repository.this.repository_url
}

output "arn" {
  description = "Repository ARN."
  value       = aws_ecr_repository.this.arn
}

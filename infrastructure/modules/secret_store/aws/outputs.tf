output "id" {
  description = "Secret ARN (Secrets Manager uses the ARN as the canonical ID)."
  value       = aws_secretsmanager_secret.this.id
}

output "name" {
  description = "Secret name."
  value       = aws_secretsmanager_secret.this.name
}

output "arn" {
  description = "Secret ARN."
  value       = aws_secretsmanager_secret.this.arn
}

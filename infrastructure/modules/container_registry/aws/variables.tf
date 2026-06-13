variable "name" {
  description = "ECR repository name (lowercase, may contain slashes for namespacing, e.g. 'maisys/api-gateway')."
  type        = string
}

variable "labels" {
  description = "Labels applied as AWS tags."
  type        = map(string)
  default     = {}
}

variable "image_tag_mutability" {
  description = "MUTABLE (default; tags can be overwritten) or IMMUTABLE (tags cannot be overwritten — safer for prod release tags)."
  type        = string
  default     = "MUTABLE"
}

variable "image_scanning_enabled" {
  description = "Enable scan-on-push for vulnerability detection. Free; no reason to disable."
  type        = bool
  default     = true
}

variable "force_delete" {
  description = "Allow terraform destroy to delete a repository containing images."
  type        = bool
  default     = false
}

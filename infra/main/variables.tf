# No defaults. deploy.yml passes every one: images from the build job, the rest from GitHub
# repository variables (docs/INFRA.md §4).

variable "project_id" {
  description = "Google Cloud project id (the one bootstrap was applied to)."
  type        = string
}

variable "api_image" {
  description = "reel-api image with its commit tag, pushed by the plan job."
  type        = string
}

variable "editor_image" {
  description = "reel-editor image with its commit tag, pushed by the plan job."
  type        = string
}

variable "email_domain" {
  description = "Verified Resend sending domain (D56); EMAIL_DOMAIN in .env.example."
  type        = string
}

variable "mail_from" {
  description = "From header of every email, an address on email_domain; MAIL_FROM in .env.example."
  type        = string
}

variable "alert_email" {
  description = "Where failure and pause alerts go; KEVIN_ALERT_EMAIL in .env.example."
  type        = string
}

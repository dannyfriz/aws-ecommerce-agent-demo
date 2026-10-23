variable "cost_center" {
  type        = string
  default     = null
  description = "Centro de costo; por defecto se usa proyecto-ambiente."
  validation {
    condition     = var.cost_center == null || can(regex("^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$", var.cost_center))
    error_message = "Usa de 1 a 128 letras, números, puntos, guiones, barras o guiones bajos."
  }
}

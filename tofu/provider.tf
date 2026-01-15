terraform {
  required_providers {
    routeros = {
      source  = "terraform-routeros/routeros"
      version = "1.98.0"
    }
  }
}

provider "routeros" {
  hosturl  = "api://192.168.88.1:8728"
  username = "admin"
  password = var.routeros_password
}

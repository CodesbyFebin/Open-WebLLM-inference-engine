terraform {
  required_version = ">= 1.6.0"
  required_providers {
    google = {source = "hashicorp/google", version = "~> 6.0"}
  }
}
variable "project_id" {type = string}
variable "region" {
  type = string
  default = "us-central1"
}
variable "cluster_name" {
  type = string
  default = "inference-lab"
}
provider "google" {
  project = var.project_id
  region = var.region
}
resource "google_container_cluster" "inference" {
  name = var.cluster_name
  location = var.region
  deletion_protection = true
  remove_default_node_pool = true
  initial_node_count = 1
  networking_mode = "VPC_NATIVE"
  ip_allocation_policy {}
  release_channel {
    channel = "REGULAR"
  }
  private_cluster_config {
    enable_private_nodes = true
    enable_private_endpoint = false
    master_ipv4_cidr_block = "172.16.0.0/28"
  }
}
resource "google_container_node_pool" "gpu" {
  name = "l4-pool"
  cluster = google_container_cluster.inference.id
  location = var.region
  node_count = 1
  node_config {
    machine_type = "g2-standard-12"
    disk_size_gb = 150
    disk_type = "pd-balanced"
    oauth_scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    guest_accelerator {
      type = "nvidia-l4"
      count = 1
      gpu_driver_installation_config {
        gpu_driver_version = "LATEST"
      }
    }
    labels = {workload = "inference"}
  }
  management {
    auto_repair = true
    auto_upgrade = true
  }
}
output "cluster_name" {value = google_container_cluster.inference.name}

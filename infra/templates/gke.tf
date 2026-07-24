# REFERENCE TEMPLATE — GKE cluster + autoscaling node pool.
# The LLM adapts THIS file (region, zone, machine type, node min/max) from
# platform.json into infra/generated/gcp/main.tf. It must keep every resource
# and output; it only changes the marked values. Known-good, hand-written.

terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
  backend "gcs" {} # state bucket supplied at `terraform init`
}

variable "project_id" {
  type = string # passed with -var at apply time (it's per-account, not in the spec)
}

provider "google" {
  project = var.project_id
  region  = "asia-south1" # <ADAPT: region>
}

resource "google_compute_network" "vpc" {
  name                    = "idea-board-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "subnet" {
  name          = "idea-board-subnet"
  region        = "asia-south1" # <ADAPT: region>
  network       = google_compute_network.vpc.id
  ip_cidr_range = "10.10.0.0/16"
}

resource "google_container_cluster" "primary" {
  name                     = "idea-board"
  location                 = "asia-south1-a" # <ADAPT: zone>
  remove_default_node_pool = true
  initial_node_count       = 1
  network                  = google_compute_network.vpc.id
  subnetwork               = google_compute_subnetwork.subnet.id
  deletion_protection      = false
}

resource "google_container_node_pool" "primary_nodes" {
  name               = "idea-board-pool"
  location           = "asia-south1-a" # <ADAPT: zone>
  cluster            = google_container_cluster.primary.name
  initial_node_count = 1

  autoscaling {
    min_node_count = 1 # <ADAPT: min_nodes>
    max_node_count = 3 # <ADAPT: max_nodes>
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  node_config {
    machine_type = "e2-small" # <ADAPT: machine_type>
    disk_size_gb = 30
    disk_type    = "pd-standard"
    oauth_scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    labels = {
      env        = "managed"
      managed-by = "terraform"
    }
  }
}

output "cluster_name" {
  value = google_container_cluster.primary.name
}

output "get_credentials_command" {
  value = "gcloud container clusters get-credentials ${google_container_cluster.primary.name} --zone asia-south1-a --project ${var.project_id}"
}

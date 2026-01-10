#!/bin/bash
# Load Talos secrets from Bitwarden Secrets Manager into environment variables
# Usage: source talos/scripts/load-talos-secrets.sh
# Requires: BWS_ACCESS_TOKEN environment variable

if [ -z "$BWS_ACCESS_TOKEN" ]; then
    echo "Error: BWS_ACCESS_TOKEN not set. Please set your Bitwarden Secrets Manager access token."
    return 1 2>/dev/null || exit 1
fi

# Helper function to get secret by key
get_secret() {
    local key=$1
    # First, list all secrets and find the one with matching key, then get its ID
    local secret_id=$(bws secret list --output json 2>/dev/null | jq -r ".[] | select(.key == \"$key\") | .id")
    if [ -z "$secret_id" ]; then
        echo ""
        return
    fi
    # Get the secret value using the ID
    bws secret get "$secret_id" --output json 2>/dev/null | jq -r '.value // ""'
}

# Export all Talos secrets from Bitwarden Secrets Manager
export TALOS_MACHINE_CA_CRT=$(get_secret "TALOS_MACHINE_CA_CRT")
export TALOS_MACHINE_CA_KEY=$(get_secret "TALOS_MACHINE_CA_KEY")
export TALOS_MACHINE_TOKEN=$(get_secret "TALOS_MACHINE_TOKEN")
export TALOS_CLUSTER_CA_CRT=$(get_secret "TALOS_CLUSTER_CA_CRT")
export TALOS_CLUSTER_CA_KEY=$(get_secret "TALOS_CLUSTER_CA_KEY")
export TALOS_CLUSTER_ID=$(get_secret "TALOS_CLUSTER_ID")
export TALOS_CLUSTER_SECRET=$(get_secret "TALOS_CLUSTER_SECRET")
export TALOS_CLUSTER_TOKEN=$(get_secret "TALOS_CLUSTER_TOKEN")
export TALOS_CLUSTER_AGGREGATORCA_CRT=$(get_secret "TALOS_CLUSTER_AGGREGATORCA_CRT")
export TALOS_CLUSTER_AGGREGATORCA_KEY=$(get_secret "TALOS_CLUSTER_AGGREGATORCA_KEY")
export TALOS_CLUSTER_ETCD_CA_CRT=$(get_secret "TALOS_CLUSTER_ETCD_CA_CRT")
export TALOS_CLUSTER_ETCD_CA_KEY=$(get_secret "TALOS_CLUSTER_ETCD_CA_KEY")
export TALOS_CLUSTER_SECRETBOXENCRYPTIONSECRET=$(get_secret "TALOS_CLUSTER_SECRETBOXENCRYPTIONSECRET")
export TALOS_CLUSTER_SERVICEACCOUNT_KEY=$(get_secret "TALOS_CLUSTER_SERVICEACCOUNT_KEY")
export TAILSCALE_AUTHKEY=$(get_secret "TAILSCALE_AUTHKEY")

echo "✓ Talos secrets loaded from Bitwarden Secrets Manager"

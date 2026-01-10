#!/bin/bash
# Populate Bitwarden Secrets Manager from existing Talos configuration files
# Usage: ./talos/scripts/populate-bitwarden-secrets.sh <project-id>
# Requires: BWS_ACCESS_TOKEN environment variable and yq

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/../.."
CONTROLPLANE_FILE="$PROJECT_ROOT/controlplane.yaml"

if [ -z "${BWS_ACCESS_TOKEN:-}" ]; then
    echo "Error: BWS_ACCESS_TOKEN not set. Please set your Bitwarden Secrets Manager access token."
    exit 1
fi

if [ $# -lt 1 ]; then
    echo "Usage: $0 <project-id>"
    echo ""
    echo "Get your project ID from Bitwarden Secrets Manager or create a new project:"
    echo "  bws project list"
    echo "  bws project create <name>"
    exit 1
fi

PROJECT_ID="$1"

if ! command -v bws &> /dev/null; then
    echo "Error: bws (Bitwarden Secrets Manager CLI) not found."
    echo "Install it from: https://bitwarden.com/help/secrets-manager-cli/"
    exit 1
fi

if ! command -v yq &> /dev/null; then
    echo "Error: yq not found. Please install yq."
    exit 1
fi

echo "Extracting secrets from $CONTROLPLANE_FILE "

# Helper function to create or update a secret
create_or_update_secret() {
    local key=$1
    local value=$2
    local note=${3:-""}

    if [ -z "$value" ] || [ "$value" = "null" ]; then
        echo "  ⚠ Skipping $key (empty or null value)"
        return
    fi
    echo "Processing secret: $key"
    echo "$value"
    # Check if secret exists
    if bws secret get "$key" --output json &>/dev/null; then
        echo "  ↻ Updating $key"
        bws secret edit --key "$key" --value "$value" --project --project-id "$PROJECT_ID" >/dev/null
    else
        echo "  ✓ Creating $key"
        bws secret create "$key" "$value" "$PROJECT_ID" >/dev/null
    fi
}

# Extract Machine CA from controlplane
MACHINE_CA_CRT=$(yq eval '.machine.ca.crt' "$CONTROLPLANE_FILE" | grep -v '^---$' | grep -v '^null$' | head -1)
MACHINE_CA_KEY=$(yq eval '.machine.ca.key' "$CONTROLPLANE_FILE" | grep -v '^---$' | grep -v '^null$' | head -1)
MACHINE_TOKEN=$(yq eval '.machine.token' "$CONTROLPLANE_FILE" | grep -v '^---$' | grep -v '^null$' | head -1)

create_or_update_secret "TALOS_MACHINE_CA_CRT" "$MACHINE_CA_CRT" "Talos Machine CA Certificate"
create_or_update_secret "TALOS_MACHINE_CA_KEY" "$MACHINE_CA_KEY" "Talos Machine CA Private Key"
create_or_update_secret "TALOS_MACHINE_TOKEN" "$MACHINE_TOKEN" "Talos Machine Token"

# Extract Cluster secrets from controlplane
CLUSTER_ID=$(yq eval '.cluster.id' "$CONTROLPLANE_FILE" | grep -v '^---$' | grep -v '^null$' | head -1)
CLUSTER_SECRET=$(yq eval '.cluster.secret' "$CONTROLPLANE_FILE" | grep -v '^---$' | grep -v '^null$' | head -1)
CLUSTER_TOKEN=$(yq eval '.cluster.token' "$CONTROLPLANE_FILE" | grep -v '^---$' | grep -v '^null$' | head -1)
CLUSTER_CA_CRT=$(yq eval '.cluster.ca.crt' "$CONTROLPLANE_FILE" | grep -v '^---$' | grep -v '^null$' | head -1)
CLUSTER_CA_KEY=$(yq eval '.cluster.ca.key' "$CONTROLPLANE_FILE" | grep -v '^---$' | grep -v '^null$' | head -1)

create_or_update_secret "TALOS_CLUSTER_ID" "$CLUSTER_ID" "Talos Cluster ID"
create_or_update_secret "TALOS_CLUSTER_SECRET" "$CLUSTER_SECRET" "Talos Cluster Secret"
create_or_update_secret "TALOS_CLUSTER_TOKEN" "$CLUSTER_TOKEN" "Talos Cluster Bootstrap Token"
create_or_update_secret "TALOS_CLUSTER_CA_CRT" "$CLUSTER_CA_CRT" "Talos Cluster CA Certificate"
create_or_update_secret "TALOS_CLUSTER_CA_KEY" "$CLUSTER_CA_KEY" "Talos Cluster CA Private Key"

# Extract Aggregator CA from controlplane
AGGREGATOR_CA_CRT=$(yq eval '.cluster.aggregatorCA.crt' "$CONTROLPLANE_FILE" | grep -v '^---$' | grep -v '^null$' | head -1)
AGGREGATOR_CA_KEY=$(yq eval '.cluster.aggregatorCA.key' "$CONTROLPLANE_FILE" | grep -v '^---$' | grep -v '^null$' | head -1)

create_or_update_secret "TALOS_CLUSTER_AGGREGATORCA_CRT" "$AGGREGATOR_CA_CRT" "Talos Aggregator CA Certificate"
create_or_update_secret "TALOS_CLUSTER_AGGREGATORCA_KEY" "$AGGREGATOR_CA_KEY" "Talos Aggregator CA Private Key"

# Extract ETCD CA from controlplane
ETCD_CA_CRT=$(yq eval '.cluster.etcd.ca.crt' "$CONTROLPLANE_FILE" | grep -v '^---$' | grep -v '^null$' | head -1)
ETCD_CA_KEY=$(yq eval '.cluster.etcd.ca.key' "$CONTROLPLANE_FILE" | grep -v '^---$' | grep -v '^null$' | head -1)

create_or_update_secret "TALOS_CLUSTER_ETCD_CA_CRT" "$ETCD_CA_CRT" "Talos ETCD CA Certificate"
create_or_update_secret "TALOS_CLUSTER_ETCD_CA_KEY" "$ETCD_CA_KEY" "Talos ETCD CA Private Key"

# Extract encryption and service account secrets from controlplane
SECRETBOX_SECRET=$(yq eval '.cluster.secretboxEncryptionSecret' "$CONTROLPLANE_FILE" | grep -v '^---$' | grep -v '^null$' | head -1)
SERVICE_ACCOUNT_KEY=$(yq eval '.cluster.serviceAccount.key' "$CONTROLPLANE_FILE" | grep -v '^---$' | grep -v '^null$' | head -1)

create_or_update_secret "TALOS_CLUSTER_SECRETBOXENCRYPTIONSECRET" "$SECRETBOX_SECRET" "Talos Secretbox Encryption Secret"
create_or_update_secret "TALOS_CLUSTER_SERVICEACCOUNT_KEY" "$SERVICE_ACCOUNT_KEY" "Talos Service Account Private Key"

echo ""
echo "✅ All secrets have been populated in Bitwarden Secrets Manager"
echo ""
echo "To use these secrets, set your BWS_ACCESS_TOKEN and source the load script:"
echo "  export BWS_ACCESS_TOKEN=<your-token>"
echo "  source talos/scripts/load-talos-secrets.sh"

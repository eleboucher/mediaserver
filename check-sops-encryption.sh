#!/bin/bash
# Check for partial encryption in sops files

failed=0

for file in "$@"; do
    # Check if file has data/stringData sections
    has_data=$(grep -qE "^(data|stringData):" "$file" && echo "yes" || echo "no")
    # Check if file has sops metadata
    has_sops=$(grep -q "^sops:" "$file" && echo "yes" || echo "no")
    # Check if file has any encrypted values
    has_enc=$(grep -q "ENC\[" "$file" && echo "yes" || echo "no")

    # Case 1: File has sops metadata and ENC markers - check for partial encryption
    if [ "$has_data" = "yes" ] && [ "$has_sops" = "yes" ] && [ "$has_enc" = "yes" ]; then
        # Check if any secret values are in plaintext (not ENC[...)
        # This looks for lines like "  KEY: value" where value doesn't start with ENC[
        if grep -A 100 "^stringData:" "$file" | grep -E "^\s+[A-Z_]+:\s+" | grep -v "^\s*#" | grep -v "ENC\[" | grep -q ":"; then
            echo "❌ ERROR: $file has mixed encrypted/plaintext values!"
            echo "   Some secrets are encrypted (ENC[...]) but others are in plaintext."
            echo "   Please decrypt the entire file first: sops -d -i $file"
            echo "   Then edit and commit - it will be automatically encrypted."
            failed=1
        fi
    # Case 2: File has data but no sops metadata - needs initial encryption
    elif [ "$has_data" = "yes" ] && [ "$has_sops" = "no" ]; then
        echo "⚠️  WARNING: $file is not encrypted!"
        echo "   Encrypting now..."
        sops --encrypt --in-place "$file"
        git add "$file"
        echo "🔐 Encrypted $file - file has been re-staged"
    fi
done

exit $failed

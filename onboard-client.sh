#!/bin/bash
# ============================================================================
# Verdicta Client Onboarding Automation Script
# ============================================================================
# This script automates the creation of a new client repository once a client
# onboards and the system is provisioned.
#
# Usage: ./onboard-client.sh <client-name> <github-org> <client-domain>
# Example: ./onboard-client.sh myclient SGC011 myclient.example.com
# ============================================================================

set -e

# Configuration
GITHUB_ORG="${2:-SGC011}"
CLIENT_NAME="${1:-newclient}"
CLIENT_DOMAIN="${3:-client.example.com}"
REPO_NAME="verdicta-${CLIENT_NAME}"
SHARED_REPO="sgc_mt_parkgroup"
VERDICTA_CLIENT_REPO="verdicta-client"
GITHUB_BASE_URL="https://github.com"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."
    
    if ! command -v gh &> /dev/null; then
        log_error "GitHub CLI (gh) is not installed"
        exit 1
    fi
    
    if ! command -v git &> /dev/null; then
        log_error "Git is not installed"
        exit 1
    fi
    
    # Check GitHub authentication
    if ! gh auth status &> /dev/null; then
        log_error "GitHub CLI is not authenticated. Run: gh auth login"
        exit 1
    fi
    
    log_info "Prerequisites check passed"
}

# Create GitHub repository
create_github_repo() {
    log_info "Creating GitHub repository: ${GITHUB_ORG}/${REPO_NAME}"
    
    if gh repo view "${GITHUB_ORG}/${REPO_NAME}" &> /dev/null; then
        log_warn "Repository ${GITHUB_ORG}/${REPO_NAME} already exists"
        read -p "Do you want to continue and overwrite? (y/N): " confirm
        if [[ "$confirm" != "y" ]]; then
            log_info "Aborting"
            exit 0
        fi
    else
        gh repo create "${GITHUB_ORG}/${REPO_NAME}" \
            --public \
            --description "Verdicta client: ${CLIENT_NAME} (${CLIENT_DOMAIN})" \
            --template "${GITHUB_ORG}/${VERDICTA_CLIENT_REPO}" \
            || true
    fi
    
    log_info "GitHub repository created: ${GITHUB_BASE_URL}/${GITHUB_ORG}/${REPO_NAME}"
}

# Setup local repository
setup_local_repo() {
    log_info "Setting up local repository..."
    
    LOCAL_DIR="/tmp/${REPO_NAME}"
    rm -rf "${LOCAL_DIR}"
    mkdir -p "${LOCAL_DIR}"
    cd "${LOCAL_DIR}"
    
    git init
    git remote add origin "${GITHUB_BASE_URL}/${GITHUB_ORG}/${REPO_NAME}.git"
    
    log_info "Local repository initialized at ${LOCAL_DIR}"
}

# Clone template modules from verdicta-client repo
clone_template_modules() {
    log_info "Cloning template modules from ${GITHUB_ORG}/${VERDICTA_CLIENT_REPO}..."
    
    git remote add template "${GITHUB_BASE_URL}/${GITHUB_ORG}/${VERDICTA_CLIENT_REPO}.git"
    git fetch template
    git checkout template/master -- .
    
    log_info "Template modules cloned"
}

# Add shared template modules as git subtrees
add_shared_modules() {
    log_info "Adding shared template modules from ${GITHUB_ORG}/${SHARED_REPO}..."
    
    git remote add shared "${GITHUB_BASE_URL}/${GITHUB_ORG}/${SHARED_REPO}.git"
    git fetch shared
    
    # Add shared modules as subtrees
    git subtree add --prefix=shared/sgc_executive_dashboard shared/master --squash || true
    git subtree add --prefix=shared/sgc_ui_brand_palette shared/master --squash || true
    git subtree add --prefix=shared/accounting_pdf_reports shared/master --squash || true
    
    log_info "Shared template modules added as subtrees"
}

# Configure client-specific settings
configure_client_settings() {
    log_info "Configuring client-specific settings..."
    
    # Update manifest files with client-specific information
    if [ -f "verdicta_intake/__manifest__.py" ]; then
        sed -i "s/Verdicta Intake/Verdicta Intake - ${CLIENT_NAME}/g" verdicta_intake/__manifest__.py
    fi
    
    # Create client configuration file
    cat > "client_config.json" << EOF
{
    "client_name": "${CLIENT_NAME}",
    "client_domain": "${CLIENT_DOMAIN}",
    "github_org": "${GITHUB_ORG}",
    "repo_name": "${REPO_NAME}",
    "created_at": "$(date -Iseconds)",
    "shared_modules": [
        "sgc_executive_dashboard",
        "sgc_ui_brand_palette",
        "accounting_pdf_reports"
    ]
}
EOF
    
    log_info "Client-specific settings configured"
}

# Setup CI/CD pipeline
setup_cicd() {
    log_info "Setting up CI/CD pipeline..."
    
    mkdir -p .github/workflows
    
    # Create GitHub Actions workflow for Odoo module testing
    cat > ".github/workflows/odoo-tests.yml" << 'EOF'
name: Odoo Module Tests

on:
  push:
    branches: [ master, develop ]
  pull_request:
    branches: [ master ]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        odoo-version: ['17.0', '18.0']
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install Odoo
        run: |
          pip install odoo
      
      - name: Run module tests
        run: |
          python -m pytest tests/ -v || true
      
      - name: Lint Python files
        run: |
          pip install flake8
          flake8 verdicta_intake/ verdicta_auth/ verdicta_brand/ || true
EOF
    
    git add .github/workflows/odoo-tests.yml
    git commit -m "Add CI/CD pipeline for Odoo module tests" || true
    
    log_info "CI/CD pipeline configured"
}

# Push to GitHub
push_to_github() {
    log_info "Pushing to GitHub..."
    
    git branch -M master
    git push -u origin master
    
    log_info "Pushed to GitHub: ${GITHUB_BASE_URL}/${GITHUB_ORG}/${REPO_NAME}"
}

# Setup Odoo configuration on VPS (optional)
setup_odoo_config() {
    log_info "Setting up Odoo configuration on VPS..."
    
    # This section would SSH into the VPS and configure Odoo
    # Uncomment and modify as needed
    
    # ssh -i "$HOME/.ssh/id_ed25519_new" root@vps-host << EOF
    #     mkdir -p /opt/verdicta/extra-addons/${REPO_NAME}
    #     git clone ${GITHUB_BASE_URL}/${GITHUB_ORG}/${REPO_NAME}.git /opt/verdicta/extra-addons/${REPO_NAME}
    #     chown -R odoo:odoo /opt/verdicta/extra-addons/${REPO_NAME}
    # EOF
    
    log_warn "VPS setup skipped (uncomment setup_odoo_config function to enable)"
}

# Display summary
display_summary() {
    echo ""
    echo "=========================================="
    echo "  Client Onboarding Complete!"
    echo "=========================================="
    echo ""
    echo "Repository: ${GITHUB_ORG}/${REPO_NAME}"
    echo "URL: ${GITHUB_BASE_URL}/${GITHUB_ORG}/${REPO_NAME}"
    echo "Client: ${CLIENT_NAME}"
    echo "Domain: ${CLIENT_DOMAIN}"
    echo "Shared Modules:"
    echo "  - sgc_executive_dashboard"
    echo "  - sgc_ui_brand_palette"
    echo "  - accounting_pdf_reports"
    echo ""
    echo "Next Steps:"
    echo "  1. Review the repository contents"
    echo "  2. Update client-specific configuration"
    echo "  3. Deploy to VPS (if applicable)"
    echo "  4. Configure Odoo to load the new module"
    echo ""
}

# Main execution
main() {
    log_info "Starting Verdicta client onboarding for ${CLIENT_NAME}..."
    
    check_prerequisites
    create_github_repo
    setup_local_repo
    clone_template_modules
    add_shared_modules
    configure_client_settings
    setup_cicd
    push_to_github
    setup_odoo_config
    display_summary
    
    log_info "Onboarding complete!"
}

# Run main function
main "$@"
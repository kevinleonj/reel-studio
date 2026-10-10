# tflint for both roots. Run from the repository root:
#   tflint --chdir infra --recursive --init  &&  tflint --chdir infra --recursive --config "$PWD/infra/.tflint.hcl"
# Versions pinned (FACTS F404); --recursive needs the absolute --config path (tflint docs, config.md).

tflint {
  required_version = "= 0.64.0"
}

config {
  call_module_type = "none" # no modules in either root
  force            = false  # findings fail the run, so make ci fails
}

# Bundled ruleset with every rule: naming, unused declarations, typed variables, pinned versions.
plugin "terraform" {
  enabled = true
  preset  = "all"
}

plugin "google" {
  enabled = true
  version = "0.40.0"
  source  = "github.com/terraform-linters/tflint-ruleset-google"
}

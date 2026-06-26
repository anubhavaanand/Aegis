package aegis.policy

default decision = {
    "allow": false,
    "requires_human": true,
    "reason": "Default deny: Policy rules not evaluated"
}

# 1. Allow low-risk tasks outright if no protected violations exist
decision = {
    "allow": true,
    "requires_human": false,
    "reason": "Low-risk compliance repair task automatically approved"
} {
    input.risk_level == "low"
    not path_violates_protected_boundaries
}

# 2. Automatically allow medium-risk repair steps if there are no unmet criteria
decision = {
    "allow": true,
    "requires_human": false,
    "reason": "Medium-risk execution without unmet criteria automatically approved"
} {
    input.risk_level == "medium"
    input.unmet_criteria_count == 0
    not path_violates_protected_boundaries
}

# 3. Restrict high-risk repairs to human oversight
decision = {
    "allow": false,
    "requires_human": true,
    "reason": "High-risk task compliance loop requires human-in-the-loop review"
} {
    input.risk_level == "high"
}

# 4. Mandatory block/escalate for critical risk tiers
decision = {
    "allow": false,
    "requires_human": true,
    "reason": "Critical risk actions require strict human evaluation and confirmation"
} {
    input.risk_level == "critical"
}

# 5. Traversal escape path guards
decision = {
    "allow": false,
    "requires_human": true,
    "reason": sprintf("Security Block: Modification of restricted system boundaries: %v", [violated_paths])
} {
    path_violates_protected_boundaries
}

# Helper rule to evaluate protected directory writes
path_violates_protected_boundaries {
    count(violated_paths) > 0
}

violated_paths[path] {
    path := input.modified_paths[_]
    is_protected(path)
}

# Explicit blacklisted patterns (e.g., configurations, secrets, env files)
is_protected(path) {
    contains(path, "secrets/")
}
is_protected(path) {
    contains(path, ".env")
}
is_protected(path) {
    contains(path, "config/")
}
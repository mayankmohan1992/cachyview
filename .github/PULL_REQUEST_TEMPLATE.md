name: Pull request
description: Describe your change
body:
  - type: textarea
    id: summary
    attributes:
      label: Summary
      description: What does this PR do and why?
    validations:
      required: true
  - type: textarea
    id: testing
    attributes:
      label: Testing
      description: How did you verify it? (pytest output, manual steps)
    validations:
      required: true
  - type: checkboxes
    id: checks
    attributes:
      label: Checklist
      options:
        - label: "`pytest` passes locally"
        - label: "Added/updated tests where relevant"
        - label: "No secrets or personal data committed"

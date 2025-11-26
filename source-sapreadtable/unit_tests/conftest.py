"""Pytest configuration for unit tests."""

import warnings

# Airbyte CDK emits ExperimentalClassWarning for protocol models; silence to keep test output clean.
warnings.filterwarnings("ignore", message=".*ExperimentalClassWarning.*")
warnings.filterwarnings("ignore", message="This class is experimental. Use at your own risk.")

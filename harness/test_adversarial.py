"""Adversarial: hostile and malformed input, driven by harness/payloads/adversarial.yaml."""

from __future__ import annotations

import pytest

from harness.adversarial import AdversarialCase, evaluate, load_cases
from harness.report import ReportCollector
from harness.settings import DEFAULT_CONFIG, HarnessSettings
from tests.framework.client import TriageClient

pytestmark = pytest.mark.adversarial

# Loaded at import time so pytest can parametrize over the payloads.
CASES = load_cases(HarnessSettings.load(DEFAULT_CONFIG).payloads_path)


def test_payload_file_is_well_formed() -> None:
    keys = [case.key for case in CASES]
    assert len(keys) == len(set(keys)), "duplicate payload ids"
    categories = {case.category for case in CASES}
    assert categories >= {"prompt_injection", "oversized", "empty", "unicode", "pii"}


@pytest.mark.parametrize("case", CASES, ids=[case.key for case in CASES])
def test_app_stays_in_control(
    client: TriageClient, case: AdversarialCase, report: ReportCollector
) -> None:
    response = client.post("/triage", json_body=case.body)
    problems = evaluate(case, response)

    report.adversarial.append(
        {
            "category": case.category,
            "id": case.id,
            "expect": case.expect,
            "status": response.status_code,
            "passed": not problems,
            "problems": problems,
        }
    )
    assert not problems, f"{case.key}: " + "; ".join(problems)

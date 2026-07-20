import asyncio
import json
from datetime import datetime, timezone

import pytest

import app.services.ai_analysis_service as ai_analysis_service
import app.services.llm_client as llm_client
from app.models.ai_analysis_job import AIAnalysisJob
from app.models.ai_finding_insight import AIFindingInsight
from app.models.finding import Finding, LocationEmbedded
from app.models.scan import Scan
from app.services import ai_provider_config_service


async def _create_active_provider():
    # _analyze_group/synthesize_scan resolve the *active* AIProviderConfig to stamp
    # provider/model_name onto the insight they save -- these unit tests monkeypatch
    # llm_client.get_completion directly (bypassing the real provider resolution inside
    # llm_client itself), but ai_analysis_service still needs an active config to exist.
    await ai_provider_config_service.create_config(
        name="Test Provider",
        provider="openai",
        model_name="gpt-4o",
        base_url=None,
        temperature=0.0,
        api_key="sk-test",
        created_by=None,
    )


def _make_finding(fingerprint, rule_id, project_id="proj-1", scan_id="scan-1", **overrides):
    now = datetime.now(timezone.utc)
    defaults = dict(
        scan_id=scan_id,
        project_id=project_id,
        fingerprint=fingerprint,
        rule_id=rule_id,
        message=f"Finding for {fingerprint}",
        location=LocationEmbedded(file="app.py", start_line=1),
        severity="high",
        cwe=["CWE-89"],
        owasp=["A03:2021"],
        rationale="because",
        remediation="fix it",
        created_at=now,
    )
    defaults.update(overrides)
    return Finding(**defaults)


def _enrichment_response(fingerprints):
    return {
        "findings": [
            {
                "fingerprint": fp,
                "owasp": ["A03:2021"],
                "cwe": ["CWE-89"],
                "cvss_score": 7.5,
                "explanation": "explained",
                "is_false_positive": False,
                "false_positive_confidence": 0.1,
                "verdict_reasoning": "looks real",
                "improved_description": "improved",
            }
            for fp in fingerprints
        ]
    }


def test_one_representative_per_rule_group_fans_out_to_all_members(client, monkeypatch):
    calls = []

    async def fake_get_completion(messages, **kwargs):
        calls.append(messages)
        payload = json.loads(messages[1]["content"])
        return _enrichment_response([f["fingerprint"] for f in payload["findings"]])

    monkeypatch.setattr(llm_client, "get_completion", fake_get_completion)

    async def run():
        await _create_active_provider()
        findings = [
            _make_finding("fp-1", "rule-a"),
            _make_finding("fp-2", "rule-a"),
            _make_finding("fp-3", "rule-b"),
        ]
        insights = await ai_analysis_service.analyze_findings_batch(findings, force=False)
        # Both rule groups' representatives fit in ONE batch => a single LLM call. Only the two
        # representatives are sent, not all three findings.
        assert len(calls) == 1
        sent = {f["fingerprint"] for f in json.loads(calls[0][1]["content"])["findings"]}
        assert sent == {"fp-1", "fp-3"}
        # Every member still gets an insight (rule-a's verdict fanned out to fp-1 AND fp-2).
        assert {i.fingerprint for i in insights} == {"fp-1", "fp-2", "fp-3"}
        by = {i.fingerprint: i for i in insights}
        # The non-representative member (fp-2) is tagged as recurring (1 sibling), not dropped.
        assert by["fp-2"].similar_finding_count == 1
        assert by["fp-1"].similar_finding_count == 1
        assert by["fp-3"].similar_finding_count == 0

    asyncio.run(run())


def test_many_rule_groups_are_split_into_provider_sized_chunks(client, monkeypatch):
    calls = []

    async def fake_get_completion(messages, **kwargs):
        calls.append(messages)
        payload = json.loads(messages[1]["content"])
        return _enrichment_response([f["fingerprint"] for f in payload["findings"]])

    monkeypatch.setattr(llm_client, "get_completion", fake_get_completion)
    # openai provider => cloud batch size; shrink it so 5 distinct rules need multiple calls.
    monkeypatch.setattr(ai_analysis_service.settings, "ai_analysis_cloud_batch_size", 2)

    async def run():
        await _create_active_provider()
        # 5 DISTINCT rules => 5 representatives, chunked 2 per call.
        findings = [_make_finding(f"fp-{i}", f"rule-{i}") for i in range(5)]
        insights = await ai_analysis_service.analyze_findings_batch(findings, force=False)
        assert len(calls) == 3  # ceil(5 / 2) chunks of representatives
        assert len(insights) == 5

    asyncio.run(run())


def test_progress_callback_reports_completed_over_total(client, monkeypatch):
    async def fake_get_completion(messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        return _enrichment_response([f["fingerprint"] for f in payload["findings"]])

    monkeypatch.setattr(llm_client, "get_completion", fake_get_completion)
    monkeypatch.setattr(ai_analysis_service.settings, "ai_analysis_cloud_batch_size", 1)

    calls: list[tuple[int, int]] = []

    async def cb(done, total):
        calls.append((done, total))

    async def run():
        await _create_active_provider()
        # 3 distinct rule groups; progress is measured in GROUPS, not raw findings.
        findings = [_make_finding(f"fp-{i}", f"rule-{i}") for i in range(3)]
        await ai_analysis_service.analyze_findings_batch(findings, force=False, progress_cb=cb)
        # batch 1 => 3 chunks: an initial (0,3), then one bump per finished group.
        assert calls[0] == (0, 3)
        assert calls[-1] == (3, 3)
        assert {c[0] for c in calls} == {0, 1, 2, 3}

    asyncio.run(run())


def test_partial_group_failure_still_persists_successful_groups(client, monkeypatch):
    async def fake_get_completion(messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        fps = [f["fingerprint"] for f in payload["findings"]]
        if "fp-boom" in fps:
            raise llm_client.LLMMalformedResponseError("bad json from the model")
        return _enrichment_response(fps)

    monkeypatch.setattr(llm_client, "get_completion", fake_get_completion)
    monkeypatch.setattr(ai_analysis_service.settings, "ai_analysis_cloud_batch_size", 1)

    async def run():
        await _create_active_provider()
        # Distinct rules so each is its own chunk; the fp-boom group fails, the others survive.
        findings = [
            _make_finding("fp-ok1", "rule-a"),
            _make_finding("fp-boom", "rule-b"),
            _make_finding("fp-ok2", "rule-c"),
        ]
        insights = await ai_analysis_service.analyze_findings_batch(findings, force=False)
        # The failing group is skipped (a coverage gap); the other two still land.
        assert {i.fingerprint for i in insights} == {"fp-ok1", "fp-ok2"}

    asyncio.run(run())


def test_all_chunks_failing_re_raises_the_real_error(client, monkeypatch):
    async def fake_get_completion(messages, **kwargs):
        raise llm_client.LLMPermanentError("400 unsupported response_format")

    monkeypatch.setattr(llm_client, "get_completion", fake_get_completion)

    async def run():
        await _create_active_provider()
        findings = [_make_finding("fp-1", "rule-a")]
        with pytest.raises(llm_client.LLMPermanentError):
            await ai_analysis_service.analyze_findings_batch(findings, force=False)

    asyncio.run(run())


def test_adjusted_severity_is_persisted_and_normalized(client, monkeypatch):
    async def fake_get_completion(messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        out = []
        for f in payload["findings"]:
            fp = f["fingerprint"]
            item = {"fingerprint": fp, "explanation": "x"}
            if fp == "fp-low":
                item["adjusted_severity"] = "LOW"  # uppercase -> normalized to "low"
                item["severity_reasoning"] = "input is parameterized"
            elif fp == "fp-bad":
                item["adjusted_severity"] = "banana"  # invalid -> dropped
                item["severity_reasoning"] = "nonsense that should be discarded"
            out.append(item)
        return {"findings": out}

    monkeypatch.setattr(llm_client, "get_completion", fake_get_completion)

    async def run():
        await _create_active_provider()
        # Distinct rules so each finding is its own representative with its own severity verdict.
        findings = [
            _make_finding("fp-low", "rule-a"),
            _make_finding("fp-bad", "rule-b"),
            _make_finding("fp-none", "rule-c"),
        ]
        insights = await ai_analysis_service.analyze_findings_batch(findings, force=True)
        by = {i.fingerprint: i for i in insights}
        assert by["fp-low"].adjusted_severity == "low"
        assert by["fp-low"].severity_reasoning == "input is parameterized"
        # An unrecognized severity is dropped along with its reasoning, rather than trusted.
        assert by["fp-bad"].adjusted_severity is None
        assert by["fp-bad"].severity_reasoning is None
        assert by["fp-none"].adjusted_severity is None

    asyncio.run(run())


def test_cached_finding_force_false_skips_llm_call(client, monkeypatch):
    calls = {"n": 0}

    async def fake_get_completion(messages, **kwargs):
        calls["n"] += 1
        return _enrichment_response(["fp-1"])

    monkeypatch.setattr(llm_client, "get_completion", fake_get_completion)

    async def run():
        finding = _make_finding("fp-1", "rule-a")
        await AIFindingInsight(fingerprint="fp-1", project_id="proj-1", explanation="cached").insert()

        insights = await ai_analysis_service.analyze_findings_batch([finding], force=False)
        assert calls["n"] == 0
        assert insights[0].explanation == "cached"

    asyncio.run(run())


def test_cache_check_batches_lookup_across_findings(client, monkeypatch):
    """The cache-check must be one batched query for the whole call, not one query per
    finding -- regression test for the N+1 fixed in analyze_findings_batch."""
    find_calls = {"n": 0}
    real_find = AIFindingInsight.find

    def counting_find(*args, **kwargs):
        find_calls["n"] += 1
        return real_find(*args, **kwargs)

    monkeypatch.setattr(AIFindingInsight, "find", counting_find)

    async def fake_get_completion(messages, **kwargs):
        raise AssertionError("fully-cached batch must not call the LLM")

    monkeypatch.setattr(llm_client, "get_completion", fake_get_completion)

    async def run():
        findings = [_make_finding(f"fp-{i}", f"rule-{i}") for i in range(5)]
        for f in findings:
            await AIFindingInsight(fingerprint=f.fingerprint, project_id="proj-1", explanation="cached").insert()

        insights = await ai_analysis_service.analyze_findings_batch(findings, force=False)
        assert len(insights) == 5
        assert find_calls["n"] == 1  # one $in query for all 5 fingerprints, not 5 find_one calls

    asyncio.run(run())


def test_force_true_overwrites_cached_insight(client, monkeypatch):
    calls = {"n": 0}

    async def fake_get_completion(messages, **kwargs):
        calls["n"] += 1
        return _enrichment_response(["fp-1"])

    monkeypatch.setattr(llm_client, "get_completion", fake_get_completion)

    async def run():
        await _create_active_provider()
        finding = _make_finding("fp-1", "rule-a")
        await AIFindingInsight(fingerprint="fp-1", project_id="proj-1", explanation="stale").insert()

        insights = await ai_analysis_service.analyze_findings_batch([finding], force=True)
        assert calls["n"] == 1
        assert insights[0].explanation == "explained"

    asyncio.run(run())


def test_analysis_confidence_is_persisted(client, monkeypatch):
    async def fake_get_completion(messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        fp = payload["findings"][0]["fingerprint"]
        return {"findings": [{"fingerprint": fp, "explanation": "x", "analysis_confidence": 0.9}]}

    monkeypatch.setattr(llm_client, "get_completion", fake_get_completion)

    async def run():
        await _create_active_provider()
        insights = await ai_analysis_service.analyze_findings_batch(
            [_make_finding("fp-1", "rule-a")], force=True
        )
        assert insights[0].analysis_confidence == 0.9

    asyncio.run(run())


def test_synthesize_scan_reports_partial_coverage(client, monkeypatch):
    async def fake_get_completion(messages, **kwargs):
        return {"summary": "model summary", "top_recommendations": []}

    monkeypatch.setattr(llm_client, "get_completion", fake_get_completion)

    async def run():
        await _create_active_provider()
        now = datetime.now(timezone.utc)
        scan = Scan(
            project_id="proj-1", scan_type="cloud", triggered_by="cloud", status="completed",
            created_at=now, updated_at=now,
        )
        await scan.insert()
        insights = [AIFindingInsight(fingerprint=f"fp-{i}", project_id="proj-1") for i in range(3)]
        # 47 intended but only 3 analyzed => partial coverage must be recorded and surfaced.
        scan_insight = await ai_analysis_service.synthesize_scan(scan, insights, intended=47)
        assert scan_insight.total_findings_intended == 47
        assert scan_insight.total_findings_analyzed == 3
        assert "3 of 47" in scan_insight.summary

    asyncio.run(run())


def test_synthesize_scan_aggregate_counts(client, monkeypatch):
    async def fake_get_completion(messages, **kwargs):
        return {"summary": "overall ok", "top_recommendations": ["do x", "do y"]}

    monkeypatch.setattr(llm_client, "get_completion", fake_get_completion)

    async def run():
        await _create_active_provider()
        now = datetime.now(timezone.utc)
        scan = Scan(
            project_id="proj-1",
            scan_type="cloud",
            triggered_by="cloud",
            status="running",
            created_at=now,
            updated_at=now,
        )
        await scan.insert()

        insights = [
            AIFindingInsight(fingerprint="fp-1", project_id="proj-1", is_false_positive=True),
            AIFindingInsight(fingerprint="fp-2", project_id="proj-1", is_false_positive=False),
            AIFindingInsight(fingerprint="fp-3", project_id="proj-1", is_false_positive=False),
        ]

        scan_insight = await ai_analysis_service.synthesize_scan(scan, insights)
        assert scan_insight.total_findings_analyzed == 3
        assert scan_insight.false_positive_count == 1
        assert scan_insight.summary == "overall ok"
        assert scan_insight.top_recommendations == ["do x", "do y"]

    asyncio.run(run())


def test_run_job_scan_all_chunks_fail_marks_failed_not_requeued(client, monkeypatch):
    """A scan job whose every chunk fails must end terminally 'failed' (started_at set,
    completed_at set) -- never left 'queued'/'running' where the poll loop would re-claim and
    re-run it forever against the provider."""

    async def fake_get_completion(messages, **kwargs):
        raise llm_client.LLMPermanentError("context size exceeded")

    monkeypatch.setattr(llm_client, "get_completion", fake_get_completion)

    async def run():
        await _create_active_provider()
        now = datetime.now(timezone.utc)
        scan = Scan(
            project_id="proj-z", scan_type="cloud", triggered_by="cloud", status="completed",
            created_at=now, updated_at=now,
        )
        await scan.insert()
        await _make_finding("fp-1", "rule-a", scan_id=str(scan.id), project_id="proj-z").insert()

        job = AIAnalysisJob(
            kind="scan", project_id="proj-z", scan_id=str(scan.id), scope_key=str(scan.id), status="queued"
        )
        await job.insert()
        await ai_analysis_service.run_job(job)

        reloaded = await AIAnalysisJob.get(job.id)
        assert reloaded.status == "failed"
        assert reloaded.started_at is not None
        assert reloaded.completed_at is not None

    asyncio.run(run())


def test_run_job_scan_partial_failure_completes_with_surviving_insights(client, monkeypatch):
    """If some chunks succeed and some fail, the scan job still COMPLETES and the surviving
    insights are persisted -- partial results beat all-or-nothing."""

    async def fake_get_completion(messages, **kwargs):
        payload = json.loads(messages[1]["content"])
        # The scan synthesis call carries "insights"; make it succeed with a summary.
        if "insights" in payload:
            return {"summary": "ok", "top_recommendations": []}
        fps = [f["fingerprint"] for f in payload["findings"]]
        if "fp-bad" in fps:
            raise llm_client.LLMPermanentError("context size exceeded")
        return _enrichment_response(fps)

    monkeypatch.setattr(llm_client, "get_completion", fake_get_completion)
    monkeypatch.setattr(ai_analysis_service.settings, "ai_analysis_cloud_batch_size", 1)

    async def run():
        await _create_active_provider()
        now = datetime.now(timezone.utc)
        scan = Scan(
            project_id="proj-p", scan_type="cloud", triggered_by="cloud", status="completed",
            created_at=now, updated_at=now,
        )
        await scan.insert()
        # Distinct rules so each is its own group/chunk; fp-bad's group fails, fp-ok's survives.
        await _make_finding("fp-ok", "rule-a", scan_id=str(scan.id), project_id="proj-p").insert()
        await _make_finding("fp-bad", "rule-b", scan_id=str(scan.id), project_id="proj-p").insert()

        job = AIAnalysisJob(
            kind="scan", project_id="proj-p", scan_id=str(scan.id), scope_key=str(scan.id), status="queued"
        )
        await job.insert()
        await ai_analysis_service.run_job(job)

        reloaded = await AIAnalysisJob.get(job.id)
        assert reloaded.status == "completed"
        # The good chunk persisted; the bad one was skipped.
        assert await AIFindingInsight.find_one(
            AIFindingInsight.fingerprint == "fp-ok", AIFindingInsight.project_id == "proj-p"
        ) is not None

    asyncio.run(run())


def test_run_job_failure_path_marks_failed_without_corrupting_insight(client, monkeypatch):
    async def fake_get_completion(messages, **kwargs):
        raise llm_client.LLMPermanentError("bad key")

    monkeypatch.setattr(llm_client, "get_completion", fake_get_completion)

    async def run():
        finding = _make_finding("fp-1", "rule-a", scan_id="scan-x", project_id="proj-x")
        await finding.insert()

        job = AIAnalysisJob(
            kind="finding",
            project_id="proj-x",
            scan_id="scan-x",
            fingerprint="fp-1",
            scope_key="fp-1",
            status="running",
        )
        await job.insert()

        await ai_analysis_service.run_job(job)

        reloaded = await AIAnalysisJob.get(job.id)
        assert reloaded.status == "failed"
        assert reloaded.error_message
        assert reloaded.completed_at is not None

        insight = await AIFindingInsight.find_one(
            AIFindingInsight.fingerprint == "fp-1", AIFindingInsight.project_id == "proj-x"
        )
        assert insight is None  # nothing written -- no corrupted/partial insight

    asyncio.run(run())

import json

from akash_agent import LLMReply, ScriptedProvider, ToolCall
from akash_api.auth import ApiKeyStore
from conftest import H, submit, wait_done


def finished(client, keys, who="researcher", query="TIC 1"):
    inv = submit(client, keys[who], query).json()["investigation_id"]
    wait_done(client, H(keys[who]), inv)
    return inv


def ask(client, keys, inv, q="What does the evidence say?", who="researcher"):
    return client.post(f"/v1/investigations/{inv}/ask", json={"question": q}, headers=H(keys[who]))


def test_deterministic_answer_when_no_model_is_configured(client, keys):
    inv = finished(client, keys)
    r = ask(client, keys, inv)
    body = r.json()
    assert r.status_code == 200 and body["mode"] == "deterministic" and body["verified"]
    assert body["note"] is None and "does not independently establish" in body["disclaimer"]
    ev = {e["evidence_id"] for e in client.get(
        f"/v1/investigations/{inv}/evidence", headers=H(keys["researcher"])).json()}
    cited = {i for s in body["statements"] for i in s["evidence_ids"]}
    assert cited and cited <= ev
    assert all("discover" not in s["text"].lower() for s in body["statements"])


def test_llm_answer_is_verified_and_audited(client, services, keys):
    inv = finished(client, keys)
    rows = client.get(f"/v1/investigations/{inv}/evidence", headers=H(keys["researcher"])).json()
    fact = next(r for r in rows if r["channel"] in ("observed_fact", "data_quality"))
    good = LLMReply(text=json.dumps({"statements": [
        {"text": "See the cited measurement row.", "kind": "recommendation", "evidence_ids": []}]}))
    services.make_llm_provider = lambda: ScriptedProvider([
        LLMReply(tool_calls=(ToolCall("1", "get_evidence", {"evidence_id": fact["evidence_id"]}),)),
        good])
    body = ask(client, keys, inv).json()
    assert body["mode"] == "llm" and fact["evidence_id"] in body["retrieved_evidence_ids"]
    with services.context() as ctx:
        acts = [(e["principal"], e["action"], e["outcome"]) for e in ApiKeyStore(ctx.conn).audit_entries()]
    assert ("rita", "agent.ask", "llm:ok") in acts


def test_unverifiable_model_answer_is_replaced_by_deterministic(client, services, keys):
    inv = finished(client, keys)
    bad = LLMReply(text=json.dumps({"statements": [
        {"text": "A new planet was discovered.", "kind": "interpretation", "evidence_ids": []}]}))
    services.make_llm_provider = lambda: ScriptedProvider([bad, bad])
    body = ask(client, keys, inv).json()
    assert body["mode"] == "deterministic" and body["verified"] and body["note"]
    assert all("discovered" not in s["text"] for s in body["statements"])


def test_other_users_investigations_are_404(client, keys):
    inv = finished(client, keys)
    assert ask(client, keys, inv, who="researcher2").status_code == 404
    assert ask(client, keys, "00000000-0000-4000-8000-000000000000").status_code == 404


def test_unauthenticated_and_bad_bodies(client, keys):
    inv = finished(client, keys)
    assert client.post(f"/v1/investigations/{inv}/ask", json={"question": "x"}).status_code == 401
    for body in ({}, {"question": ""}, {"question": "x" * 501}, {"question": "x", "tools": ["w"]}):
        r = client.post(f"/v1/investigations/{inv}/ask", json=body, headers=H(keys["researcher"]))
        assert r.status_code in (400, 422)


def test_unfinished_investigation_is_409(client, keys):
    from conftest import GATE
    GATE.clear()
    inv = submit(client, keys["researcher"], "TIC 9").json()["investigation_id"]
    assert ask(client, keys, inv).status_code == 409
    GATE.set()
    wait_done(client, H(keys["researcher"]), inv)


def test_agent_has_its_own_rate_limit(client, services, keys):
    inv = finished(client, keys)
    services.settings.api_agent_rate_per_min = 2
    codes = [ask(client, keys, inv).status_code for _ in range(4)]
    assert codes[:2] == [200, 200] and 429 in codes

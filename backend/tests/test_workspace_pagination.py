import pytest
from test_api_output import output_client


@pytest.mark.parametrize("kind", ["collections", "collectors", "runs", "ai-runs"])
def test_workspace_lists_have_numbered_metadata_and_empty_boundaries(tmp_path, kind):
    with output_client(tmp_path) as (_, client):
        result = client.get(f"/api/v1/{kind}", params={"page": 999, "q": "no-match-pagination"})
        assert result.status_code == 200
        assert result.json()["items"] == []
        assert result.json()["pagination"] == {"page": 1, "pageSize": 50, "totalPages": 1, "total": 0}
        assert client.get(f"/api/v1/{kind}?page=0").status_code == 422


def test_runs_page_and_global_counts_extend_beyond_two_hundred(tmp_path):
    with output_client(tmp_path) as (store, client):
        collector = store.create_collector("Source", "Collect", "https://example.com/list", "example.com")
        for index in range(205):
            store.save_run({"id": f"run_{index:03}", "collectorId": collector["id"],
                            "collectorName": "Literal 100%_", "status": "failed" if index == 0 else "succeeded"})
        first = client.get("/api/v1/runs?page=1&limit=50").json()
        last = client.get("/api/v1/runs?page=5&limit=50").json()
        assert first["pagination"]["total"] == 205
        assert first["counts"] == {"all": 205, "attention": 1, "succeeded": 204}
        assert len(last["items"]) == 5
        assert not {r["id"] for r in first["items"]} & {r["id"] for r in last["items"]}
        found = client.get("/api/v1/runs", params={"page": 1, "q": "run_000", "status": "attention"}).json()
        assert found["total"] == 1
        assert found["items"][0]["id"] == "run_000"
        assert client.get("/api/v1/runs", params={"page": 1, "q": "100%_"}).json()["total"] == 205


def test_collector_attention_includes_latest_run_outside_recent_history(tmp_path):
    with output_client(tmp_path) as (store, client):
        source = store.create_collector("Old source", "Collect", "https://example.com/old", "example.com")
        store.save_run({"id": "old_failed", "collectorId": source["id"], "status": "failed"})
        source["latestRunId"] = "old_failed"
        store.save_collector(source)
        for index in range(201):
            store.save_run({"id": f"new_{index}", "collectorId": source["id"], "status": "succeeded"})
        result = client.get("/api/v1/collectors?page=1&view=attention&q=Old").json()
        assert result["total"] == 1
        assert result["latestRuns"][0]["id"] == "old_failed"
        assert result["counts"]["attention"] >= 1


def test_requirements_and_sources_filter_before_slicing(tmp_path):
    with output_client(tmp_path) as (store, client):
        for index in range(55):
            store.create_collection(f"Requirement {index:03}", "Pagination goal")
            store.create_collector(f"Source {index:03}", "Collect", f"https://example.com/{index}", "example.com")
        for kind, term in (("collections", "Requirement"), ("collectors", "Source")):
            first = client.get(f"/api/v1/{kind}", params={"page": 1, "q": term}).json()
            last = client.get(f"/api/v1/{kind}", params={"page": 2, "q": term}).json()
            assert first["total"] == 55
            assert last["pagination"]["totalPages"] == 2
            assert len(first["items"]) == 50 and len(last["items"]) == 5
            assert not {row["id"] for row in first["items"]} & {row["id"] for row in last["items"]}
        match = client.get("/api/v1/collectors?page=999&q=Source%20000").json()
        assert match["total"] == 1 and match["pagination"]["page"] == 1


def test_ai_tasks_page_and_review_filters_include_old_history(tmp_path):
    with output_client(tmp_path) as (store, client):
        collector = store.create_collector("AI source", "Collect", "https://example.com/ai", "example.com")
        for index in range(205):
            operation_id = f"op_{index}"
            store.save_operation({"id": operation_id, "kind": "explore", "status": "succeeded"}, collector["id"])
            store.save_ai_run({"id": f"ai_{index:03}", "collectorId": collector["id"], "collectorName": "AI source",
                               "sourceUrl": f"https://example.com/{index}", "status": "succeeded", "resultStatus": "candidate_ready",
                               "reviewStatus": "ready_review" if index == 0 else "published"}, collector["id"], operation_id)
        last = client.get("/api/v1/ai-runs?page=5").json()
        assert last["pagination"]["total"] == 205 and len(last["items"]) == 5
        review = client.get("/api/v1/ai-runs?page=1&status=review").json()
        assert review["counts"]["review"] == 1 and review["total"] == 1
        assert review["items"][0]["id"] == "ai_000"
        assert review["items"][0]["collectionAttribution"]["collectionId"] == collector["collectionId"]

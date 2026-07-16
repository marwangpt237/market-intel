"""Tests for Phase 3 — expanded REST API (entities, trends, knowledge_graph)."""
import sys, os, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api.app import app
    return TestClient(app)


# ─── Entities ──────────────────────────────────────────────────────────

def test_list_entities(client):
    response = client.get("/api/v1/entities")
    assert response.status_code == 200
    data = response.json()
    assert "entities" in data
    assert "total" in data


def test_list_entities_filtered(client):
    response = client.get("/api/v1/entities?type=company")
    assert response.status_code == 200


def test_list_companies(client):
    response = client.get("/api/v1/entities/companies")
    assert response.status_code == 200
    data = response.json()
    assert "companies" in data


def test_list_products(client):
    response = client.get("/api/v1/entities/products")
    assert response.status_code == 200
    data = response.json()
    assert "products" in data


def test_list_topics(client):
    response = client.get("/api/v1/entities/topics")
    assert response.status_code == 200
    data = response.json()
    assert "topics" in data


def test_get_entity(client):
    response = client.get("/api/v1/entities/company/hubspot")
    assert response.status_code == 200
    data = response.json()
    assert data["entity_type"] == "company"
    assert data["entity_name"] == "hubspot"


# ─── Trends ────────────────────────────────────────────────────────────

def test_list_trends(client):
    response = client.get("/api/v1/trends")
    assert response.status_code == 200
    data = response.json()
    assert "trends" in data
    assert "total" in data


def test_hot_trends(client):
    response = client.get("/api/v1/trends/hot")
    assert response.status_code == 200


def test_rising_trends(client):
    response = client.get("/api/v1/trends/rising")
    assert response.status_code == 200


def test_trends_timeline(client):
    response = client.get("/api/v1/trends/timeline?days=7")
    assert response.status_code == 200
    data = response.json()
    assert "timeline" in data
    assert data["days"] == 7


# ─── Opportunities ─────────────────────────────────────────────────────

def test_list_opportunities(client):
    response = client.get("/api/v1/opportunities")
    assert response.status_code == 200
    data = response.json()
    assert "opportunities" in data


def test_top_opportunities(client):
    response = client.get("/api/v1/opportunities/top")
    assert response.status_code == 200


# ─── Knowledge Graph ───────────────────────────────────────────────────

def test_get_knowledge_graph(client):
    response = client.get("/api/v1/knowledge-graph")
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data
    assert "edges" in data


def test_knowledge_graph_stats(client):
    response = client.get("/api/v1/knowledge-graph/stats")
    assert response.status_code == 200
    data = response.json()
    assert "stats" in data


# ─── Evidence ──────────────────────────────────────────────────────────

def test_list_evidence(client):
    response = client.get("/api/v1/evidence")
    assert response.status_code == 200
    data = response.json()
    assert "evidence" in data


def test_evidence_for_claim(client):
    response = client.get("/api/v1/evidence/claim/nonexistent")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0

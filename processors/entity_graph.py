"""
Entity graph builder — creates a relationship graph from extracted entities.

Links:
- Company ↔ Product (company makes product)
- Company ↔ Competitor (competitor relationship)
- Company ↔ Pain Point (users complain about company's X)
- Topic ↔ Company (company mentioned in topic cluster)
- Buying Signal ↔ Company (purchase intent for company's product)

Output: a graph dict with nodes and edges, stored in metadata.
"""
from __future__ import annotations

from collections import defaultdict, Counter
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor


class EntityGraphProcessor(BaseProcessor):
    name = "entity_graph"

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        nodes: dict[str, dict] = {}  # node_id → {type, name, mentions}
        edges: list[dict] = []
        edge_set: set[str] = set()  # for dedup: "source|target|type"

        for item in items:
            entities = item.metadata.get("entities", {})
            companies = entities.get("companies", [])
            products = entities.get("products", [])
            pain_points = item.metadata.get("pain_points", [])
            competitor_mentions = item.metadata.get("competitor_mentions", [])
            buying_signals = item.metadata.get("buying_signals", [])
            cluster_label = item.metadata.get("cluster_label", "")

            # Add company nodes
            for company in companies:
                node_id = f"company:{company}"
                if node_id not in nodes:
                    nodes[node_id] = {"type": "company", "name": company, "mentions": 0, "pain_points": 0, "buying_signals": 0}
                nodes[node_id]["mentions"] += 1

            # Add product nodes + company→product edges
            for product in products:
                node_id = f"product:{product}"
                if node_id not in nodes:
                    nodes[node_id] = {"type": "product", "name": product, "mentions": 0}
                nodes[node_id]["mentions"] += 1

                # Try to link product to a company (simple heuristic: same item)
                for company in companies:
                    edge_key = f"company:{company}|product:{product}|makes"
                    if edge_key not in edge_set:
                        edges.append({"source": f"company:{company}", "target": f"product:{product}", "type": "makes"})
                        edge_set.add(edge_key)

            # Company ↔ Pain Point edges
            for pp in pain_points:
                for company in companies:
                    edge_key = f"company:{company}|pain:{pp.get('category', '')}|has_pain"
                    if edge_key not in edge_set:
                        edges.append({
                            "source": f"company:{company}",
                            "target": f"pain:{pp.get('category', 'unknown')}",
                            "type": "has_pain",
                            "severity": pp.get("severity", "medium"),
                        })
                        edge_set.add(edge_key)
                    # Increment company pain point count
                    company_node = nodes.get(f"company:{company}")
                    if company_node:
                        company_node["pain_points"] += 1

            # Company ↔ Competitor edges
            for comp_mention in competitor_mentions:
                comp = comp_mention.get("competitor", "")
                signal = comp_mention.get("signal", "mention")
                if comp:
                    edge_key = f"competitor:{comp}|signal:{signal}|competitor_mentioned"
                    if edge_key not in edge_set:
                        edges.append({
                            "source": f"competitor:{comp}",
                            "target": f"signal:{signal}",
                            "type": "competitor_signal",
                        })
                        edge_set.add(edge_key)

            # Topic ↔ Company edges
            if cluster_label and cluster_label != "uncategorized":
                for company in companies:
                    edge_key = f"topic:{cluster_label}|company:{company}|mentioned_in"
                    if edge_key not in edge_set:
                        edges.append({
                            "source": f"topic:{cluster_label}",
                            "target": f"company:{company}",
                            "type": "mentioned_in_topic",
                        })
                        edge_set.add(edge_key)

            # Buying Signal ↔ Company edges
            if buying_signals:
                for company in companies:
                    company_node = nodes.get(f"company:{company}")
                    if company_node:
                        company_node["buying_signals"] += 1
                    edge_key = f"company:{company}|buying|has_buying_signal"
                    if edge_key not in edge_set:
                        edges.append({
                            "source": f"company:{company}",
                            "target": "signal:buying_intent",
                            "type": "has_buying_signal",
                        })
                        edge_set.add(edge_key)

        # Add pain point nodes
        for item in items:
            for pp in item.metadata.get("pain_points", []):
                cat = pp.get("category", "unknown")
                node_id = f"pain:{cat}"
                if node_id not in nodes:
                    nodes[node_id] = {"type": "pain_point", "name": cat, "mentions": 0, "severity": pp.get("severity", "medium")}
                nodes[node_id]["mentions"] += 1

        # Add topic nodes
        topic_counts: Counter = Counter()
        for item in items:
            label = item.metadata.get("cluster_label", "")
            if label and label != "uncategorized":
                topic_counts[label] += 1
        for label, count in topic_counts.items():
            nodes[f"topic:{label}"] = {"type": "topic", "name": label, "mentions": count}

        graph = {
            "nodes": list(nodes.values()),
            "node_ids": list(nodes.keys()),
            "edges": edges,
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "companies": len([n for n in nodes.values() if n["type"] == "company"]),
                "products": len([n for n in nodes.values() if n["type"] == "product"]),
                "pain_points": len([n for n in nodes.values() if n["type"] == "pain_point"]),
                "topics": len([n for n in nodes.values() if n["type"] == "topic"]),
            },
        }

        # Store graph on first item for report generator
        if items:
            items[0].metadata["_entity_graph"] = graph

        self._logger.info(
            f"Entity graph: {graph['stats']['total_nodes']} nodes, {graph['stats']['total_edges']} edges",
            extra=graph["stats"]
        )
        return items

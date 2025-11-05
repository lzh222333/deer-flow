# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import os
import requests

from src.rag.retriever import Chunk, Document, Resource, Retriever


def parse_uri(uri: str) -> tuple[str, str]:
    """
    Parse URI into dataset_id and collection_id if present.
    Format: dataset_id:collection_id (collection_id is optional)
    """
    parts = uri.split(":", 1)
    dataset_id = parts[0]
    collection_id = parts[1] if len(parts) > 1 else ""
    return dataset_id, collection_id


class FastGPTProvider(Retriever):
    """
    FastGPTProvider is a provider that uses FastGPT to retrieve documents.
    """

    api_url: str
    api_key: str
    top_k: int
    page_size: int

    def __init__(self):
        api_url = os.getenv("FASTGPT_API_URL")
        if not api_url:
            raise ValueError("FASTGPT_API_URL is not set")
        self.api_url = api_url.rstrip("/")

        api_key = os.getenv("FASTGPT_API_KEY")
        if not api_key:
            raise ValueError("FASTGPT_API_KEY is not set")
        self.api_key = api_key

        # Optional configuration
        self.top_k = int(os.getenv("FASTGPT_TOP_K", "100"))
        self.page_size = int(os.getenv("FASTGPT_PAGE_SIZE", "10"))

    def _get_headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def list_resources(self, query: str | None = None) -> list[Resource]:
        """
        List all available knowledge bases (datasets) from FastGPT.
        """
        headers = self._get_headers()
        payload = {"parentId": ""}

        try:
            response = requests.post(
                f"{self.api_url}/api/core/dataset/list?parentId=",
                headers=headers,
                json=payload,
                timeout=30,
            )

            response.raise_for_status()
            result = response.json()

            if result.get("code") != 200:
                raise Exception(f"API returned error code: {result.get('code')}")

            datasets = result.get("data", [])
            resources = []

            for dataset in datasets:
                dataset_id = dataset.get("_id")
                name = dataset.get("name")
                if dataset_id and name:
                    resources.append(
                        Resource(
                            uri=dataset_id,
                            title=name,
                            description=f"FastGPT 知识库: {name}",
                        )
                    )

            # If query is provided, filter resources by name
            if query:
                query_lower = query.lower()
                resources = [
                    r
                    for r in resources
                    if query_lower in r.title.lower()
                    or query_lower in (r.description or "").lower()
                ]

            return resources

        except Exception as e:
            raise Exception(f"Failed to list FastGPT resources: {str(e)}")

    def query_relevant_documents(
        self, query: str, resources: list[Resource] = []
    ) -> list[Document]:
        """
        Query relevant documents from selected resources using FastGPT's searchTest API.
        """
        if not resources:
            return []

        headers = self._get_headers()
        all_documents = {}

        for resource in resources:
            dataset_id, _ = parse_uri(resource.uri)

            # Use FastGPT's searchTest API for vector search
            payload = {
                "datasetId": dataset_id,
                "text": query,
                "limit": 10000,  # Default limit as recommended in docs
                "similarity": 0.5,  # Default similarity threshold
                "searchMode": "embedding",  # Vector semantic search
            }

            try:
                response = requests.post(
                    f"{self.api_url}/api/core/dataset/searchTest",
                    headers=headers,
                    json=payload,
                    timeout=30,
                )

                response.raise_for_status()
                result = response.json()

                if result.get("code") != 200:
                    raise Exception(f"API returned error code: {result.get('code')}")

                search_results = result.get("data", [])
                
                # Group results by sourceName if available
                for item in search_results:
                    content = item.get("q", "")
                    similarity = item.get("score", 0.0)
                    source_name = item.get("sourceName", "Unknown Source")

                    # Use sourceName as document title and create a unique ID
                    doc_id = f"{dataset_id}_{source_name}"
                    
                    if doc_id not in all_documents:
                        all_documents[doc_id] = Document(
                            id=doc_id,
                            title=source_name,
                            chunks=[],
                        )

                    chunk = Chunk(content=content, similarity=similarity)
                    all_documents[doc_id].chunks.append(chunk)

            except Exception as e:
                raise Exception(
                    f"Failed to query documents from dataset {dataset_id}: {str(e)}"
                )

        # Convert to list and sort by total similarity score
        document_list = list(all_documents.values())
        document_list.sort(
            key=lambda doc: sum(chunk.similarity for chunk in doc.chunks),
            reverse=True,
        )

        # Return top_k documents
        return document_list[: self.top_k]
# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import os
from typing import List, Optional
from urllib.parse import urlparse

import requests

from src.rag.retriever import Chunk, Document, Resource, Retriever


class FastGPTProvider(Retriever):
    """
    FastGPTProvider is a provider that uses FastGPT to retrieve documents.
    """

    api_url: str
    api_key: str
    page_size: int = 10
    
    def __init__(self):
        api_url = os.getenv("FASTGPT_API_URL")
        if not api_url:
            raise ValueError("FASTGPT_API_URL is not set")
        # 确保URL不以斜杠结尾，以避免重复的斜杠
        self.api_url = api_url.rstrip("/")

        api_key = os.getenv("FASTGPT_API_KEY")
        if not api_key:
            raise ValueError("FASTGPT_API_KEY is not set")
        self.api_key = api_key

        page_size = os.getenv("FASTGPT_PAGE_SIZE")
        if page_size:
            try:
                self.page_size = int(page_size)
            except ValueError:
                print(f"Warning: Invalid FASTGPT_PAGE_SIZE value: {page_size}, using default: {self.page_size}")
        
        # 配置API路径（可根据实际FastGPT API文档调整）
        self.retrieve_api_path = os.getenv("FASTGPT_RETRIEVE_API_PATH", "/api/core/dataset/retrieve")
        self.list_api_path = os.getenv("FASTGPT_LIST_API_PATH", "/api/core/dataset/list")

    def query_relevant_documents(
        self, query: str, resources: list[Resource] = []
    ) -> list[Document]:
        if not resources:
            return []

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # 收集所有的知识库ID
        dataset_ids: list[str] = []
        for resource in resources:
            try:
                dataset_id, _ = parse_uri(resource.uri)
                if dataset_id:
                    dataset_ids.append(dataset_id)
            except Exception as e:
                print(f"Warning: Failed to parse resource URI {resource.uri}: {e}")

        if not dataset_ids:
            return []

        # 构建请求参数
        payload = {
            "question": query,
            "datasetIds": dataset_ids,
            "topK": self.page_size
        }

        try:
            # 调用FastGPT的检索API
            response = requests.post(
                f"{self.api_url}{self.retrieve_api_path}",
                headers=headers,
                json=payload,
                timeout=30  # 添加超时设置
            )

            if response.status_code != 200:
                raise Exception(f"Failed to query documents: {response.status_code} - {response.text}")

            result = response.json()
            
            # 检查响应格式
            if result.get("code") != 200:
                raise Exception(f"API returned error code: {result.get('code')}, message: {result.get('message')}")

            # 处理返回的数据，考虑多种可能的响应格式
            data = result.get("data", {})
            # 支持多种可能的文档列表键名
            chunks = data.get("documents", [])
            if not chunks:
                chunks = data.get("docs", [])
            if not chunks:
                chunks = data.get("items", [])
            
            # 按文档ID分组
            docs_dict: dict[str, Document] = {}
            
            for chunk_data in chunks:
                # 支持多种可能的文档ID键名
                doc_id = chunk_data.get("doc_id") or chunk_data.get("id") or chunk_data.get("documentId")
                # 支持多种可能的文档名称键名
                doc_name = chunk_data.get("doc_name") or chunk_data.get("name") or chunk_data.get("title")
                # 支持多种可能的内容键名
                content = chunk_data.get("content", "") or chunk_data.get("text", "")
                # 支持多种可能的分数键名
                score = chunk_data.get("score", 0.0) or chunk_data.get("similarity", 0.0)
                
                if not doc_id:
                    continue
                
                if doc_id not in docs_dict:
                    docs_dict[doc_id] = Document(
                        id=doc_id,
                        title=doc_name or f"Document {doc_id}",
                        chunks=[]
                    )
                
                # 添加chunk到对应的文档
                chunk = Chunk(content=content, similarity=float(score))
                docs_dict[doc_id].chunks.append(chunk)
            
            return list(docs_dict.values())
            
        except requests.Timeout:
            raise Exception("Request to FastGPT API timed out")
        except requests.RequestException as e:
            raise Exception(f"Network error when querying FastGPT API: {e}")

    def list_resources(self, query: str | None = None) -> list[Resource]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        params = {}
        if query:
            params["name"] = query

        try:
            # 调用FastGPT的获取知识库列表API
            response = requests.get(
                f"{self.api_url}{self.list_api_path}",
                headers=headers,
                params=params,
                timeout=30  # 添加超时设置
            )

            if response.status_code != 200:
                raise Exception(f"Failed to list resources: {response.status_code} - {response.text}")

            result = response.json()
            
            # 检查响应格式
            if result.get("code") != 200:
                raise Exception(f"API returned error code: {result.get('code')}, message: {result.get('message')}")

            resources = []
            
            # 处理返回的数据，考虑多种可能的响应格式
            data = result.get("data", [])
            # 支持多种可能的数据列表格式
            if isinstance(data, dict):
                items = data.get("items", [])
                if not items:
                    items = data.get("datasets", [])
            else:
                items = data
                
            for item in items:
                # 支持多种可能的ID键名
                dataset_id = item.get("id") or item.get("datasetId")
                # 支持多种可能的名称键名
                name = item.get("name", "") or item.get("title", "")
                # 支持多种可能的描述键名
                description = item.get("description", "") or item.get("desc", "")
                
                if not dataset_id:
                    continue
                
                resource = Resource(
                    uri=f"rag://dataset/{dataset_id}",
                    title=name or f"Dataset {dataset_id}",
                    description=description
                )
                resources.append(resource)

            return resources
            
        except requests.Timeout:
            raise Exception("Request to FastGPT API timed out")
        except requests.RequestException as e:
            raise Exception(f"Network error when listing FastGPT resources: {e}")


def parse_uri(uri: str) -> tuple[str, str]:
    """
    Parse the resource URI to extract dataset_id and optional document_id.
    
    Args:
        uri: The resource URI in format "rag://dataset/{dataset_id}#optional_document_id"
        
    Returns:
        A tuple of (dataset_id, document_id)
    """
    parsed = urlparse(uri)
    if parsed.scheme != "rag":
        raise ValueError(f"Invalid URI scheme: {parsed.scheme}, expected 'rag'")
    
    # 提取dataset_id，格式为 rag://dataset/{dataset_id}
    path_parts = parsed.path.strip("/").split("/")
    if len(path_parts) < 2 or path_parts[0] != "dataset":
        raise ValueError(f"Invalid URI path format: {parsed.path}, expected '/dataset/{{dataset_id}}'")
    
    dataset_id = path_parts[1]
    # fragment部分作为document_id（如果有）
    document_id = parsed.fragment
    
    return dataset_id, document_id
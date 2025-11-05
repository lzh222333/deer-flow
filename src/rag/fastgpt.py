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
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Invalid FASTGPT_PAGE_SIZE value: {page_size}, using default: {self.page_size}")
        
        # 配置API路径（根据FastGPT API文档）
        self.retrieve_api_path = os.getenv("FASTGPT_RETRIEVE_API_PATH", "/api/core/dataset/retrieve")
        self.list_api_path = os.getenv("FASTGPT_LIST_API_PATH", "/api/core/dataset/list")
        self.collection_list_api_path = os.getenv("FASTGPT_COLLECTION_LIST_API_PATH", "/api/core/dataset/collection/listV2")
        self.collection_data_list_api_path = os.getenv("FASTGPT_COLLECTION_DATA_LIST_API_PATH", "/api/core/dataset/data/v2/list")
        self.data_detail_api_path = os.getenv("FASTGPT_DATA_DETAIL_API_PATH", "/api/core/dataset/data/detail")
        self.collection_detail_api_path = os.getenv("FASTGPT_COLLECTION_DETAIL_API_PATH", "/api/core/dataset/collection/detail")

    def query_relevant_documents(
        self, query: str, resources: list[Resource] = []
    ) -> list[Document]:
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"Querying relevant documents with query: {query}")
        logger.info(f"Number of resources provided: {len(resources)}")
        
        if not resources:
            logger.info("No resources provided, returning empty list")
            return []

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        documents = []
        
        # 处理每个资源
        for resource in resources:
            try:
                # 解析URI以获取dataset_id, collection_id和document_id
                dataset_id, collection_id, document_id = parse_uri(resource.uri)
                logger.info(f"Parsed resource URI {resource.uri}: dataset_id={dataset_id}, collection_id={collection_id}, document_id={document_id}")
                
                # 根据不同的URI类型进行不同的处理
                if document_id:
                    # 1. 获取单条数据详情
                    logger.info(f"Fetching single data detail for document_id: {document_id}")
                    doc = self._fetch_single_data_detail(headers, document_id, dataset_id, collection_id, resource)
                    if doc:
                        documents.append(doc)
                elif collection_id:
                    # 2. 获取集合的数据列表
                    logger.info(f"Fetching collection data list for collection_id: {collection_id}")
                    collection_docs = self._fetch_collection_data_list(headers, collection_id, dataset_id, query, resource)
                    documents.extend(collection_docs)
                else:
                    # 3. 使用通用检索API查询整个知识库
                    logger.info(f"Using general retrieve API for dataset_id: {dataset_id}")
                    dataset_docs = self._fetch_from_dataset(headers, dataset_id, query, resource)
                    documents.extend(dataset_docs)
                    
            except Exception as e:
                logger.error(f"Error processing resource {resource.uri}: {e}")
                # 继续处理其他资源，不中断整体流程
                continue
        
        logger.info(f"Successfully retrieved {len(documents)} documents from all resources")
        return documents
    
    def _fetch_single_data_detail(self, headers, document_id, dataset_id, collection_id, resource):
        """获取单条数据详情"""
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            logger.info(f"Making request to FastGPT data detail API: {self.api_url}{self.data_detail_api_path}")
            params = {"id": document_id}
            
            response = requests.get(
                f"{self.api_url}{self.data_detail_api_path}",
                headers=headers,
                params=params,
                timeout=30
            )
            
            logger.info(f"API response status code: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"Failed to fetch data detail: {response.status_code} - {response.text}")
                return None
            
            result = response.json()
            if result.get("code") != 200:
                logger.error(f"API returned error code: {result.get('code')}, message: {result.get('message')}")
                return None
            
            data = result.get("data", {})
            content = data.get("q", "") or data.get("content", "") or data.get("text", "")
            
            # 如果有答案字段，也添加到内容中
            answer = data.get("a", "")
            if answer:
                content = f"{content}\n\nAnswer: {answer}"
            
            # 获取索引信息作为额外内容
            indexes = data.get("indexes", [])
            for idx in indexes:
                idx_text = idx.get("text", "")
                if idx_text and idx_text != content:
                    content = f"{content}\n\n{idx_text}"
            
            if content:
                doc = Document(
                    id=document_id,
                    title=data.get("sourceName", resource.title) or f"Document {document_id}",
                    chunks=[Chunk(content=content, similarity=1.0)]  # 单条数据相似度设为1.0
                )
                logger.info(f"Created document from single data: ID={document_id}")
                return doc
            
            return None
            
        except Exception as e:
            logger.error(f"Error fetching single data detail: {e}")
            return None
    
    def _fetch_collection_data_list(self, headers, collection_id, dataset_id, query, resource):
        """获取集合的数据列表"""
        import logging
        logger = logging.getLogger(__name__)
        
        documents = []
        
        try:
            # 先获取集合详情以获取名称等信息
            collection_name = resource.title
            try:
                collection_detail_response = requests.get(
                    f"{self.api_url}{self.collection_detail_api_path}",
                    headers=headers,
                    params={"id": collection_id},
                    timeout=30
                )
                
                if collection_detail_response.status_code == 200:
                    detail_result = collection_detail_response.json()
                    if detail_result.get("code") == 200:
                        detail_data = detail_result.get("data", {})
                        collection_name = detail_data.get("name", collection_name)
            except Exception as e:
                logger.warning(f"Failed to get collection detail: {e}")
                # 继续执行，使用现有名称
            
            logger.info(f"Making request to FastGPT collection data list API: {self.api_url}{self.collection_data_list_api_path}")
            payload = {
                "offset": 0,
                "pageSize": self.page_size,
                "collectionId": collection_id,
                "searchText": query or ""
            }
            
            response = requests.post(
                f"{self.api_url}{self.collection_data_list_api_path}",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            logger.info(f"API response status code: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"Failed to fetch collection data list: {response.status_code} - {response.text}")
                return documents
            
            result = response.json()
            if result.get("code") != 200:
                logger.error(f"API returned error code: {result.get('code')}, message: {result.get('message')}")
                return documents
            
            data_list = result.get("data", {}).get("list", [])
            logger.info(f"Retrieved {len(data_list)} items from collection {collection_id}")
            
            for item in data_list:
                item_id = item.get("_id") or item.get("id")
                content = item.get("q", "") or item.get("content", "") or item.get("text", "")
                
                # 如果有答案字段，也添加到内容中
                answer = item.get("a", "")
                if answer:
                    content = f"{content}\n\nAnswer: {answer}"
                
                if item_id and content:
                    doc = Document(
                        id=item_id,
                        title=f"{collection_name} - Item {item.get('chunkIndex', 0)}",
                        chunks=[Chunk(content=content, similarity=1.0)]  # 默认相似度
                    )
                    documents.append(doc)
                    logger.info(f"Added document from collection item: ID={item_id}")
            
        except Exception as e:
            logger.error(f"Error fetching collection data list: {e}")
        
        return documents
    
    def _fetch_from_dataset(self, headers, dataset_id, query, resource):
        """使用通用检索API查询整个知识库"""
        import logging
        logger = logging.getLogger(__name__)
        
        documents = []
        
        try:
            # 构建请求参数
            payload = {
                "question": query,
                "datasetIds": [dataset_id],
                "topK": self.page_size
            }
            
            logger.info(f"Making request to FastGPT retrieve API: {self.api_url}{self.retrieve_api_path}")
            logger.info(f"Request payload: {payload}")
            
            # 调用FastGPT的检索API
            response = requests.post(
                f"{self.api_url}{self.retrieve_api_path}",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            logger.info(f"API response status code: {response.status_code}")
            
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
            
            logger.info(f"Retrieved {len(chunks)} chunks from dataset {dataset_id}")
            
            # 按文档ID分组
            docs_dict: dict[str, Document] = {}
            
            for chunk_data in chunks:
                # 支持多种可能的文档ID键名
                doc_id = chunk_data.get("doc_id") or chunk_data.get("id") or chunk_data.get("documentId") or chunk_data.get("_id")
                # 支持多种可能的文档名称键名
                doc_name = chunk_data.get("doc_name") or chunk_data.get("name") or chunk_data.get("title") or resource.title
                # 支持多种可能的内容键名
                content = chunk_data.get("content", "") or chunk_data.get("text", "") or chunk_data.get("q", "")
                # 支持多种可能的分数键名
                score = chunk_data.get("score", 0.0) or chunk_data.get("similarity", 0.0)
                
                if not doc_id:
                    logger.warning(f"Skipping chunk without document ID: {chunk_data}")
                    continue
                
                if doc_id not in docs_dict:
                    docs_dict[doc_id] = Document(
                        id=doc_id,
                        title=doc_name or f"Document {doc_id}",
                        chunks=[]
                    )
                    logger.info(f"Created new document: ID={doc_id}, Title={docs_dict[doc_id].title}")
                
                # 添加chunk到对应的文档
                chunk = Chunk(content=content, similarity=float(score))
                docs_dict[doc_id].chunks.append(chunk)
                logger.debug(f"Added chunk to document {doc_id} with similarity score: {score}")
            
            documents = list(docs_dict.values())
            logger.info(f"Successfully created {len(documents)} documents from dataset {dataset_id}")
            
        except Exception as e:
            logger.error(f"Error fetching from dataset {dataset_id}: {e}")
        
        return documents

    def list_resources(self, query: str | None = None) -> list[Resource]:
        import logging
        logger = logging.getLogger(__name__)
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        resources = []
        
        try:
            # 1. 首先获取知识库列表
            # 根据API文档，parentId需要作为URL参数传递，而不是在请求体中
            dataset_params = {
                "parentId": ""  # 根目录下的知识库，空字符串或null
            }
            
            # 添加查询参数
            if query:
                dataset_params["name"] = query
                logger.info(f"Filtering datasets with query: {query}")

            logger.info(f"Making request to FastGPT API for datasets: {self.api_url}{self.list_api_path}")
            logger.info(f"Request params: {dataset_params}")

            # 调用FastGPT的获取知识库列表API，使用POST请求，parentId作为URL参数
            dataset_response = requests.post(
                f"{self.api_url}{self.list_api_path}",
                headers=headers,
                params=dataset_params,
                json={},  # 请求体可以为空，parentId已在URL参数中传递
                timeout=30  # 添加超时设置
            )

            logger.info(f"API response status code for datasets: {dataset_response.status_code}")

            if dataset_response.status_code != 200:
                raise Exception(f"Failed to list datasets: {dataset_response.status_code} - {dataset_response.text}")

            dataset_result = dataset_response.json()
            
            # 检查响应格式
            if dataset_result.get("code") != 200:
                raise Exception(f"API returned error code: {dataset_result.get('code')}, message: {dataset_result.get('message')}")

            # 处理返回的数据，根据API文档直接使用data数组
            datasets = dataset_result.get("data", [])
            logger.info(f"Retrieved {len(datasets)} datasets from FastGPT")
            
            # 为每个知识库获取集合列表
            for dataset in datasets:
                dataset_id = dataset.get("_id") or dataset.get("id") or dataset.get("datasetId")
                dataset_name = dataset.get("name", "") or dataset.get("title", "")
                
                if not dataset_id:
                    logger.warning(f"Skipping dataset without ID: {dataset}")
                    continue
                
                # 添加知识库本身作为资源
                dataset_resource = Resource(
                    uri=f"rag://dataset/{dataset_id}",
                    title=dataset_name or f"Dataset {dataset_id}",
                    description=dataset.get("intro", "")
                )
                resources.append(dataset_resource)
                logger.info(f"Added dataset resource: ID={dataset_id}, Name={dataset_name}")
                
                # 不获取和添加集合级资源，只返回知识库级资源

            logger.info(f"Successfully parsed {len(resources)} total resources (datasets and collections)")
            return resources
            
        except requests.Timeout:
            logger.error("Request to FastGPT API timed out")
            raise Exception("Request to FastGPT API timed out")
        except requests.RequestException as e:
            logger.error(f"Network error when listing FastGPT resources: {e}")
            raise Exception(f"Network error when listing FastGPT resources: {e}")
        except Exception as e:
            logger.error(f"Error listing FastGPT resources: {e}")
            raise


def parse_uri(uri: str) -> tuple[str, str, Optional[str]]:
    """
    Parse the resource URI to extract dataset_id, optional collection_id and optional document_id.
    
    Args:
        uri: The resource URI in format:
             - "rag://dataset/{dataset_id}#optional_document_id"
             - "rag://dataset/{dataset_id}/collection/{collection_id}#optional_document_id"
             - 也支持直接传入dataset_id（特殊处理）
        
    Returns:
        A tuple of (dataset_id, collection_id, document_id)
    """
    parsed = urlparse(uri)
    
    # 特殊处理：如果URI直接是一个ID或没有rag://前缀，可能是直接传入的dataset_id
    if parsed.scheme != "rag" or not uri.startswith("rag://"):
        # 检查是否是一个纯dataset_id格式
        import re
        if re.match(r'^[a-zA-Z0-9]+$', uri.strip("/")):
            return uri.strip("/"), None, None
        
        # 如果是纯路径格式如 /dataset_id
        if uri.startswith("/"):
            dataset_id = uri.strip("/")
            if re.match(r'^[a-zA-Z0-9]+$', dataset_id):
                return dataset_id, None, None
        
        raise ValueError(f"Invalid URI scheme: {parsed.scheme}, expected 'rag'")
    
    # 提取dataset_id和可能的collection_id
    path_parts = parsed.path.strip("/").split("/")
    
    # 支持两种格式：/dataset/{dataset_id} 或 直接是dataset_id
    if len(path_parts) == 1:
        # 可能是直接的dataset_id
        return path_parts[0], None, parsed.fragment
    elif len(path_parts) >= 2 and path_parts[0] == "dataset":
        dataset_id = path_parts[1]
        collection_id = None
        
        # 检查是否包含collection
        if len(path_parts) >= 4 and path_parts[2] == "collection":
            collection_id = path_parts[3]
        
        return dataset_id, collection_id, parsed.fragment
    else:
        raise ValueError(f"Invalid URI path format: {parsed.path}, expected '/dataset/{{dataset_id}}' or '/dataset/{{dataset_id}}/collection/{{collection_id}}'")